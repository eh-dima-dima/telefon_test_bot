from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import AuthenticatedSession, CooldownActive, Database, DuplicateUser
from .n8n import CallRequest, CallTrigger, N8nCallTrigger
from .phone import InvalidPhoneNumber, normalize_phone
from .rate_limit import SlidingWindowRateLimiter
from .security import (
    hash_password,
    new_token,
    normalize_email,
    token_hash,
    tokens_equal,
    verify_password,
)

PACKAGE_DIR = Path(__file__).parent
SESSION_COOKIE = "__Host-session"
PREAUTH_CSRF_COOKIE = "preauth_csrf"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.app.state.settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response


class RequestSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > 16_384:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        return await call_next(request)


class DisabledCallTrigger:
    async def trigger(self, request: CallRequest):  # pragma: no cover - guarded before use
        raise RuntimeError("Calls are disabled")


def create_app(*, settings: Settings, call_trigger: CallTrigger | None = None) -> FastAPI:
    database = Database(settings.database_path)
    auth_limiter = SlidingWindowRateLimiter()
    if call_trigger is None:
        if settings.calls_enabled and settings.n8n_webhook_url:
            call_trigger = N8nCallTrigger(
                webhook_url=settings.n8n_webhook_url,
                timeout_seconds=settings.request_timeout_seconds,
                bearer_token=settings.n8n_webhook_token,
            )
        else:
            call_trigger = DisabledCallTrigger()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(
        title="Telefoncaller",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.call_trigger = call_trigger
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[settings.origin_host, "testserver", "127.0.0.1", "localhost"],
    )
    app.add_middleware(RequestSizeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

    def origin_is_valid(request: Request) -> bool:
        origin = request.headers.get("origin")
        return origin == settings.app_origin

    def client_key(request: Request, action: str) -> str:
        host = request.client.host if request.client else "unknown"
        return f"{action}:{host}"

    def current_session(request: Request) -> AuthenticatedSession | None:
        raw_token = request.cookies.get(SESSION_COOKIE)
        if not raw_token:
            return None
        return database.get_session(token_hash(raw_token))

    def set_preauth_csrf(response: HTMLResponse, token: str) -> None:
        response.set_cookie(
            PREAUTH_CSRF_COOKIE,
            token,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=1800,
        )

    def render_auth(
        request: Request,
        template: str,
        *,
        status_code: int = 200,
        errors: list[str] | None = None,
        values: dict[str, str] | None = None,
    ) -> HTMLResponse:
        csrf_token = new_token()
        response = templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "csrf_token": csrf_token,
                "errors": errors or [],
                "values": values or {},
            },
            status_code=status_code,
        )
        set_preauth_csrf(response, csrf_token)
        return response

    def establish_session(response: RedirectResponse, user_id: str) -> None:
        raw_token = new_token()
        database.create_session(
            user_id=user_id,
            token_hash=token_hash(raw_token),
            csrf_token=new_token(),
            ttl_seconds=settings.session_ttl_seconds,
        )
        response.set_cookie(
            SESSION_COOKIE,
            raw_token,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=settings.session_ttl_seconds,
        )
        response.delete_cookie(PREAUTH_CSRF_COOKIE, path="/")

    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"status": "ok"} if database.healthcheck() else {"status": "error"}, status_code=200)

    @app.get("/")
    async def root(request: Request):
        destination = "/app" if current_session(request) else "/login"
        return RedirectResponse(destination, status_code=303)

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        if current_session(request):
            return RedirectResponse("/app", status_code=303)
        return render_auth(request, "register.html")

    @app.post("/register", response_class=HTMLResponse)
    async def register_submit(
        request: Request,
        csrf_token: Annotated[str, Form()],
        name: Annotated[str, Form()] = "",
        email: Annotated[str, Form()] = "",
        phone: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
    ):
        if not origin_is_valid(request) or not tokens_equal(csrf_token, request.cookies.get(PREAUTH_CSRF_COOKIE)):
            return HTMLResponse("Forbidden", status_code=403)

        if not auth_limiter.allow(client_key(request, "register"), limit=5, window_seconds=600):
            return render_auth(
                request,
                "register.html",
                status_code=429,
                errors=["Zu viele Registrierungsversuche. Bitte versuchen Sie es später erneut."],
                values={"name": name.strip(), "email": normalize_email(email), "phone": phone.strip()},
            )

        clean_name = name.strip()
        clean_email = normalize_email(email)
        errors: list[str] = []
        if not clean_name or len(clean_name) > 100:
            errors.append("Bitte geben Sie Ihren Namen ein.")
        if not EMAIL_RE.fullmatch(clean_email) or len(clean_email) > 254:
            errors.append("Bitte geben Sie eine gültige E-Mail-Adresse ein.")
        try:
            clean_phone = normalize_phone(phone, default_region=settings.default_phone_region)
        except InvalidPhoneNumber:
            clean_phone = ""
            errors.append("Bitte geben Sie eine gültige Telefonnummer ein.")
        if len(password) < 12:
            errors.append("Das Passwort muss mindestens 12 Zeichen lang sein.")
        if len(password) > 128:
            errors.append("Das Passwort darf höchstens 128 Zeichen lang sein.")
        values = {"name": clean_name, "email": clean_email, "phone": phone.strip()}
        if errors:
            return render_auth(request, "register.html", status_code=422, errors=errors, values=values)

        try:
            user = database.create_user(
                name=clean_name,
                email=clean_email,
                phone=clean_phone,
                password_hash=hash_password(password),
            )
        except DuplicateUser:
            return render_auth(
                request,
                "register.html",
                status_code=409,
                errors=["Diese E-Mail-Adresse oder Telefonnummer ist bereits registriert."],
                values=values,
            )
        response = RedirectResponse("/app", status_code=303)
        establish_session(response, user.id)
        return response

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if current_session(request):
            return RedirectResponse("/app", status_code=303)
        return render_auth(request, "login.html")

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        csrf_token: Annotated[str, Form()],
        email: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
    ):
        if not origin_is_valid(request) or not tokens_equal(csrf_token, request.cookies.get(PREAUTH_CSRF_COOKIE)):
            return HTMLResponse("Forbidden", status_code=403)
        if not auth_limiter.allow(client_key(request, "login"), limit=10, window_seconds=300):
            return render_auth(
                request,
                "login.html",
                status_code=429,
                errors=["Zu viele Anmeldeversuche. Bitte versuchen Sie es später erneut."],
                values={"email": normalize_email(email)},
            )
        clean_email = normalize_email(email)
        user = database.get_user_by_email(clean_email)
        if user is None or not verify_password(user.password_hash, password):
            return render_auth(
                request,
                "login.html",
                status_code=401,
                errors=["E-Mail oder Passwort ist falsch."],
                values={"email": clean_email},
            )
        response = RedirectResponse("/app", status_code=303)
        establish_session(response, user.id)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        session = current_session(request)
        csrf = request.headers.get("x-csrf-token")
        if not origin_is_valid(request) or session is None or not tokens_equal(csrf, session.csrf_token):
            return HTMLResponse("Forbidden", status_code=403)
        raw_token = request.cookies.get(SESSION_COOKIE)
        if raw_token:
            database.delete_session(token_hash(raw_token))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/app", response_class=HTMLResponse)
    async def dashboard(request: Request):
        session = current_session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="app.html",
            context={
                "user": session.user,
                "csrf_token": session.csrf_token,
                "calls_enabled": settings.calls_enabled,
            },
        )

    @app.post("/api/calls")
    async def trigger_call(request: Request):
        session = current_session(request)
        if session is None:
            return JSONResponse({"accepted": False, "message": "Bitte melden Sie sich an."}, status_code=401)
        csrf = request.headers.get("x-csrf-token")
        if not origin_is_valid(request) or not tokens_equal(csrf, session.csrf_token):
            return JSONResponse({"accepted": False, "message": "Ungültige Anfrage."}, status_code=403)
        if not settings.calls_enabled:
            return JSONResponse(
                {"accepted": False, "message": "Anrufe sind in dieser Umgebung deaktiviert."},
                status_code=503,
            )
        try:
            attempt_id = database.reserve_call(
                user_id=session.user.id,
                cooldown_seconds=settings.call_cooldown_seconds,
            )
        except CooldownActive:
            return JSONResponse(
                {"accepted": False, "message": "Bitte warten Sie kurz, bevor Sie erneut anrufen."},
                status_code=429,
            )

        result = await app.state.call_trigger.trigger(
            CallRequest(
                name=session.user.name,
                email=session.user.email,
                phone=session.user.phone,
            )
        )
        database.complete_call(
            attempt_id=attempt_id,
            accepted=result.accepted,
            http_status=result.http_status,
            session_id=result.session_id,
            error=result.error,
        )
        if result.accepted:
            return JSONResponse(
                {
                    "accepted": True,
                    "session_id": result.session_id,
                    "vapi_call_id": result.vapi_call_id,
                    "message": "Wir rufen Sie jetzt an.",
                },
                status_code=202,
            )

        if result.http_status == 409:
            status, message = 409, "Die Telefonleitung ist momentan belegt."
        elif result.http_status == 422:
            status, message = 422, result.error or "Anrufe sind derzeit nicht möglich."
        elif result.http_status == 400:
            status, message = 502, "Die Anrufdaten konnten nicht verarbeitet werden."
        elif result.http_status in {401, 403, 404, 429, 500, 502, 503, 504}:
            status, message = 503, "Der Anrufdienst ist momentan nicht verfügbar."
        else:
            status, message = 502, "Der Anruf konnte nicht gestartet werden."
        return JSONResponse(
            {
                "accepted": False,
                "session_id": result.session_id,
                "message": message,
            },
            status_code=status,
        )

    return app

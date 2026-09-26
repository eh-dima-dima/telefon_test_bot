from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class SettingsError(ValueError):
    """Raised when deployment settings are unsafe or incomplete."""


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_origin: str
    database_path: Path
    session_secret: str
    cookie_secure: bool = True
    calls_enabled: bool = False
    n8n_webhook_url: str | None = None
    n8n_webhook_token: str | None = None
    default_phone_region: str = "DE"
    call_cooldown_seconds: int = 60
    session_ttl_seconds: int = 30 * 24 * 60 * 60
    request_timeout_seconds: float = 12.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_path", Path(self.database_path))
        object.__setattr__(self, "app_origin", self.app_origin.rstrip("/"))
        origin = urlparse(self.app_origin)
        if origin.scheme not in {"http", "https"} or not origin.hostname:
            raise SettingsError("APP_ORIGIN must be an absolute HTTP(S) URL")
        if len(self.session_secret) < 32:
            raise SettingsError("SESSION_SECRET must contain at least 32 characters")
        if self.call_cooldown_seconds < 1:
            raise SettingsError("CALL_COOLDOWN_SECONDS must be positive")
        if self.calls_enabled:
            if not self.n8n_webhook_url:
                raise SettingsError("N8N_WEBHOOK_URL is required when calls are enabled")
            webhook = urlparse(self.n8n_webhook_url)
            if webhook.scheme != "https" or not webhook.hostname:
                raise SettingsError("N8N_WEBHOOK_URL must use HTTPS")

    @property
    def origin_host(self) -> str:
        host = urlparse(self.app_origin).hostname
        assert host is not None
        return host

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.getenv("SESSION_SECRET", "")
        if not secret:
            raise SettingsError("SESSION_SECRET is required")
        return cls(
            app_origin=os.getenv("APP_ORIGIN", "http://localhost:8000"),
            database_path=Path(os.getenv("DATABASE_PATH", "/data/caller.db")),
            session_secret=secret,
            cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), default=True),
            calls_enabled=_as_bool(os.getenv("CALLS_ENABLED"), default=False),
            n8n_webhook_url=os.getenv("N8N_WEBHOOK_URL") or None,
            n8n_webhook_token=os.getenv("N8N_WEBHOOK_TOKEN") or None,
            default_phone_region=os.getenv("DEFAULT_PHONE_REGION", "DE"),
            call_cooldown_seconds=int(os.getenv("CALL_COOLDOWN_SECONDS", "60")),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", str(30 * 24 * 60 * 60))),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
        )

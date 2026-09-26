from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from caller_app.config import Settings
from caller_app.main import create_app
from caller_app.n8n import CallRequest, CallTriggerResult


@dataclass
class FakeCallTrigger:
    result: CallTriggerResult = field(
        default_factory=lambda: CallTriggerResult(
            accepted=True,
            http_status=202,
            session_id="call-test-1",
            vapi_call_id="vapi-test-1",
            error=None,
        )
    )
    calls: list[CallRequest] = field(default_factory=list)

    async def trigger(self, request: CallRequest) -> CallTriggerResult:
        self.calls.append(request)
        return self.result


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        app_origin="https://caller.example.test",
        database_path=tmp_path / "caller.db",
        session_secret="test-secret-that-is-long-enough-for-tests",
        cookie_secure=True,
        calls_enabled=True,
        n8n_webhook_url="https://n8n.example.test/webhook/start-call",
        call_cooldown_seconds=60,
    )


@pytest.fixture
def fake_trigger() -> FakeCallTrigger:
    return FakeCallTrigger()


@pytest.fixture
def client(settings: Settings, fake_trigger: FakeCallTrigger) -> TestClient:
    app = create_app(settings=settings, call_trigger=fake_trigger)
    with TestClient(app, base_url=settings.app_origin) as test_client:
        yield test_client


def csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF field missing"
    return match.group(1)


def csrf_meta_from_html(html: str) -> str:
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "CSRF meta missing"
    return match.group(1)


def register(
    client: TestClient,
    *,
    name: str = "Max Mustermann",
    email: str = "max@example.com",
    phone: str = "+49 151 12345678",
    password: str = "correct horse battery staple",
):
    page = client.get("/register")
    csrf = csrf_from_html(page.text)
    return client.post(
        "/register",
        data={
            "csrf_token": csrf,
            "name": name,
            "email": email,
            "phone": phone,
            "password": password,
        },
        headers={"Origin": "https://caller.example.test"},
        follow_redirects=False,
    )


def logout(client: TestClient):
    page = client.get("/app")
    csrf = csrf_meta_from_html(page.text)
    return client.post(
        "/logout",
        headers={
            "Origin": "https://caller.example.test",
            "X-CSRF-Token": csrf,
        },
        follow_redirects=False,
    )

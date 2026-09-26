from dataclasses import replace

from fastapi.testclient import TestClient

from caller_app.main import create_app
from conftest import FakeCallTrigger, csrf_meta_from_html, register


def test_call_posts_exact_profile_payload_to_n8n(client: TestClient, fake_trigger: FakeCallTrigger):
    assert register(client).status_code == 303
    page = client.get("/app")
    csrf = csrf_meta_from_html(page.text)

    response = client.post(
        "/api/calls",
        headers={
            "Origin": "https://caller.example.test",
            "X-CSRF-Token": csrf,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "session_id": "call-test-1",
        "vapi_call_id": "vapi-test-1",
        "message": "Wir rufen Sie jetzt an.",
    }
    assert len(fake_trigger.calls) == 1
    assert fake_trigger.calls[0].as_payload() == {
        "name": "Max Mustermann",
        "email": "max@example.com",
        "phone": "+49" + "15112345678",
        "source": "app",
    }


def test_call_requires_csrf(client: TestClient, fake_trigger: FakeCallTrigger):
    assert register(client).status_code == 303

    response = client.post(
        "/api/calls",
        headers={"Origin": "https://caller.example.test"},
    )

    assert response.status_code == 403
    assert fake_trigger.calls == []


def test_calls_disabled_never_invokes_trigger(settings, fake_trigger: FakeCallTrigger):
    disabled = replace(settings, calls_enabled=False, n8n_webhook_url=None)
    app = create_app(settings=disabled, call_trigger=fake_trigger)
    with TestClient(app, base_url=disabled.app_origin) as client:
        assert register(client).status_code == 303
        page = client.get("/app")
        csrf = csrf_meta_from_html(page.text)
        response = client.post(
            "/api/calls",
            headers={"Origin": disabled.app_origin, "X-CSRF-Token": csrf},
        )

    assert response.status_code == 503
    assert response.json()["accepted"] is False
    assert fake_trigger.calls == []


def test_double_click_is_blocked_by_persistent_cooldown(client: TestClient, fake_trigger: FakeCallTrigger):
    assert register(client).status_code == 303
    page = client.get("/app")
    csrf = csrf_meta_from_html(page.text)
    headers = {"Origin": "https://caller.example.test", "X-CSRF-Token": csrf}

    first = client.post("/api/calls", headers=headers)
    second = client.post("/api/calls", headers=headers)

    assert first.status_code == 202
    assert second.status_code == 429
    assert "Bitte warten" in second.json()["message"]
    assert len(fake_trigger.calls) == 1

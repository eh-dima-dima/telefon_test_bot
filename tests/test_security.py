from fastapi.testclient import TestClient

from caller_app.main import create_app


def test_healthz_checks_database(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_headers_are_present(client: TestClient):
    response = client.get("/login")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "max-age=" in response.headers["strict-transport-security"]


def test_container_healthcheck_host_is_allowed(settings, fake_trigger):
    app = create_app(settings=settings, call_trigger=fake_trigger)
    with TestClient(app, base_url="http://127.0.0.1:8000") as local_client:
        response = local_client.get("/healthz")

    assert response.status_code == 200

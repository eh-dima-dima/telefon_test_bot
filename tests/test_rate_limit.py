from fastapi.testclient import TestClient

from conftest import csrf_from_html


def test_login_is_rate_limited_after_repeated_failures(client: TestClient):
    for _ in range(10):
        page = client.get("/login")
        csrf = csrf_from_html(page.text)
        response = client.post(
            "/login",
            data={
                "csrf_token": csrf,
                "email": "missing@example.com",
                "password": "incorrect password value",
            },
            headers={"Origin": "https://caller.example.test"},
        )
        assert response.status_code == 401

    page = client.get("/login")
    csrf = csrf_from_html(page.text)
    blocked = client.post(
        "/login",
        data={
            "csrf_token": csrf,
            "email": "missing@example.com",
            "password": "incorrect password value",
        },
        headers={"Origin": "https://caller.example.test"},
    )

    assert blocked.status_code == 429
    assert "Zu viele Anmeldeversuche" in blocked.text


def test_registration_is_rate_limited(client: TestClient):
    for _ in range(5):
        page = client.get("/register")
        csrf = csrf_from_html(page.text)
        response = client.post(
            "/register",
            data={
                "csrf_token": csrf,
                "name": "",
                "email": "wrong",
                "phone": "123",
                "password": "short",
            },
            headers={"Origin": "https://caller.example.test"},
        )
        assert response.status_code == 422

    page = client.get("/register")
    csrf = csrf_from_html(page.text)
    blocked = client.post(
        "/register",
        data={
            "csrf_token": csrf,
            "name": "",
            "email": "wrong",
            "phone": "123",
            "password": "short",
        },
        headers={"Origin": "https://caller.example.test"},
    )

    assert blocked.status_code == 429
    assert "Zu viele Registrierungsversuche" in blocked.text

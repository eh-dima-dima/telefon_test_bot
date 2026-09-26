from fastapi.testclient import TestClient

from conftest import csrf_from_html, logout, register


def test_registration_creates_authenticated_session(client: TestClient):
    response = register(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    cookie = response.headers["set-cookie"]
    assert "session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie

    dashboard = client.get("/app")
    assert dashboard.status_code == 200
    assert "Max Mustermann" in dashboard.text
    assert "Подзвонити" not in dashboard.text
    assert "Jetzt anrufen" in dashboard.text
    assert dashboard.text.count("<button") == 1


def test_registration_rejects_invalid_fields(client: TestClient):
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
    assert "Bitte geben Sie Ihren Namen ein" in response.text
    assert "gültige E-Mail-Adresse" in response.text
    assert "gültige Telefonnummer" in response.text
    assert "mindestens 12 Zeichen" in response.text


def test_duplicate_email_is_case_insensitive(client: TestClient):
    assert register(client).status_code == 303
    assert logout(client).status_code == 303

    response = register(client, email="MAX@EXAMPLE.COM", phone="+49 160 12345678")

    assert response.status_code == 409
    assert "bereits registriert" in response.text


def test_login_uses_generic_error_for_unknown_email_and_wrong_password(client: TestClient):
    assert register(client).status_code == 303
    assert logout(client).status_code == 303

    errors = []
    for email, password in [
        ("missing@example.com", "incorrect password value"),
        ("max@example.com", "incorrect password value"),
    ]:
        page = client.get("/login")
        csrf = csrf_from_html(page.text)
        response = client.post(
            "/login",
            data={"csrf_token": csrf, "email": email, "password": password},
            headers={"Origin": "https://caller.example.test"},
        )
        assert response.status_code == 401
        errors.append("E-Mail oder Passwort ist falsch" in response.text)

    assert errors == [True, True]


def test_unauthenticated_dashboard_redirects_to_login(client: TestClient):
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

from pathlib import Path

import pytest

from caller_app.config import Settings, SettingsError


def test_calls_are_disabled_by_default(tmp_path: Path):
    settings = Settings(
        app_origin="http://localhost:8000",
        database_path=tmp_path / "app.db",
        session_secret="a-long-development-secret-for-tests",
        cookie_secure=False,
    )

    assert settings.calls_enabled is False


def test_enabled_calls_require_https_webhook(tmp_path: Path):
    with pytest.raises(SettingsError, match="HTTPS"):
        Settings(
            app_origin="https://caller.example.test",
            database_path=tmp_path / "app.db",
            session_secret="a-long-development-secret-for-tests",
            calls_enabled=True,
            n8n_webhook_url="http://n8n.example.test/webhook/start-call",
        )

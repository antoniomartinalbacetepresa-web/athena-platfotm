import hashlib
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"
_NEW_PASSWORD = "NewCorrectHorseBatteryStaple!"


class _FakeMailer:
    def __init__(self) -> None:
        self.challenges = []

    def send(self, challenge) -> None:
        self.challenges.append(challenge)


def _configure(monkeypatch, tmp_path: Path) -> Path:
    database_path = tmp_path / "athena.db"
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)
    return database_path


def _register(email: str = "recover@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 201, response.text


def _login(email: str = "recover@example.com", password: str = _PASSWORD):
    return client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": password},
    )


def test_recovery_resets_password_once_and_revokes_existing_sessions(
    monkeypatch, tmp_path: Path
) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    _register()
    old_access_token = _login().json()["access_token"]
    fake_mailer = _FakeMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: fake_mailer)

    requested = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "recover@example.com"},
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["status"] == "recovery_requested"
    assert len(fake_mailer.challenges) == 1
    challenge = fake_mailer.challenges[0]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT token_hash FROM athena_password_recovery_tokens LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(challenge.token.encode("utf-8")).hexdigest()
    assert row[0] != challenge.token

    reset = client.post(
        "/api/v1/auth/recovery/reset",
        json={"token": challenge.token, "newPassword": _NEW_PASSWORD},
    )
    assert reset.status_code == 204, reset.text

    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {old_access_token}"},
    ).status_code == 401
    assert _login(password=_PASSWORD).status_code == 401
    assert _login(password=_NEW_PASSWORD).status_code == 200

    reused = client.post(
        "/api/v1/auth/recovery/reset",
        json={"token": challenge.token, "newPassword": "AnotherSecurePassword123!"},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"] == "Token de recuperación no válido o caducado."


def test_recovery_request_does_not_reveal_unknown_accounts(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    fake_mailer = _FakeMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: fake_mailer)

    unknown = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "unknown@example.com"},
    )
    assert unknown.status_code == 202
    assert unknown.json() == {
        "status": "recovery_requested",
        "message": "Si existe una cuenta válida para ese email, se enviarán instrucciones de recuperación.",
    }
    assert fake_mailer.challenges == []


def test_recovery_request_is_persistently_rate_limited(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path)
    fake_mailer = _FakeMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: fake_mailer)

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/recovery/request",
            json={"email": "rate@example.com"},
        )
        assert response.status_code == 202

    blocked = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "rate@example.com"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "900"


def test_recovery_delivery_fails_closed_without_secure_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("ATHENA_RECOVERY_SMTP_HOST", raising=False)
    monkeypatch.delenv("ATHENA_RECOVERY_FROM_EMAIL", raising=False)
    monkeypatch.delenv("ATHENA_RECOVERY_PUBLIC_URL", raising=False)

    response = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "recover@example.com"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Recuperación de cuenta no configurada de forma segura."

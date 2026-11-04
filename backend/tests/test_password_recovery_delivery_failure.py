import hashlib
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"


class _FailingMailer:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def send(self, challenge) -> None:
        self.tokens.append(challenge.token)
        raise auth_api.PasswordRecoveryDeliveryError("simulated delivery failure")


def _configure(monkeypatch, tmp_path: Path) -> Path:
    database_path = tmp_path / "athena.db"
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)
    return database_path


def test_failed_recovery_delivery_invalidates_undelivered_token(
    monkeypatch, tmp_path: Path
) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "delivery-failure@example.com", "password": _PASSWORD},
    )
    assert registered.status_code == 201, registered.text

    mailer = _FailingMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: mailer)

    requested = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "delivery-failure@example.com"},
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["status"] == "recovery_requested"
    assert len(mailer.tokens) == 1

    token = mailer.tokens[0]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT consumed_at
            FROM athena_password_recovery_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    assert row is not None
    assert row[0] is not None

    rejected = client.post(
        "/api/v1/auth/recovery/reset",
        json={
            "token": token,
            "newPassword": "NewCorrectHorseBatteryStaple!",
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"] == "Token de recuperación no válido o caducado."

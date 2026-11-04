from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app
from app.services.password_recovery_mailer import (
    PasswordRecoveryDeliveryError,
    PasswordRecoveryMailer,
)
from app.services.password_recovery_service import PasswordRecoveryChallenge


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"
_NEW_PASSWORD = "DifferentHorseBatteryStaple!"
_GENERIC_RESPONSE = {
    "status": "recovery_requested",
    "message": "Si existe una cuenta válida para ese email, se enviarán instrucciones de recuperación.",
}


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def _register(monkeypatch, tmp_path: Path, email: str = "user@example.com") -> None:
    _configure(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 201, response.text


class _CapturingMailer:
    def __init__(self) -> None:
        self.challenges: list[PasswordRecoveryChallenge] = []

    def send(self, challenge: PasswordRecoveryChallenge) -> None:
        self.challenges.append(challenge)


class _FailingMailer(_CapturingMailer):
    def send(self, challenge: PasswordRecoveryChallenge) -> None:
        self.challenges.append(challenge)
        raise PasswordRecoveryDeliveryError("simulated delivery failure")


def test_recovery_request_does_not_reveal_account_existence_or_delivery_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _register(monkeypatch, tmp_path)

    success_mailer = _CapturingMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: success_mailer)
    existing = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "user@example.com"},
    )
    assert existing.status_code == 202
    assert existing.json() == _GENERIC_RESPONSE
    assert len(success_mailer.challenges) == 1

    missing_mailer = _CapturingMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: missing_mailer)
    missing = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "missing@example.com"},
    )
    assert missing.status_code == existing.status_code
    assert missing.json() == existing.json()
    assert missing_mailer.challenges == []

    failing_mailer = _FailingMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: failing_mailer)
    failed_delivery = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "user@example.com"},
    )
    assert failed_delivery.status_code == existing.status_code
    assert failed_delivery.json() == existing.json()
    assert len(failing_mailer.challenges) == 1

    public_payload = str(failed_delivery.json())
    failed_challenge = failing_mailer.challenges[0]
    assert failed_challenge.token not in public_payload
    assert failed_challenge.email not in public_payload


def test_undelivered_recovery_token_is_invalidated(monkeypatch, tmp_path: Path) -> None:
    _register(monkeypatch, tmp_path)
    failing_mailer = _FailingMailer()
    monkeypatch.setattr(auth_api, "_recovery_mailer", lambda: failing_mailer)

    requested = client.post(
        "/api/v1/auth/recovery/request",
        json={"email": "user@example.com"},
    )
    assert requested.status_code == 202
    assert len(failing_mailer.challenges) == 1

    reset = client.post(
        "/api/v1/auth/recovery/reset",
        json={
            "token": failing_mailer.challenges[0].token,
            "newPassword": _NEW_PASSWORD,
        },
    )
    assert reset.status_code == 400
    assert reset.json()["detail"] == "Token de recuperación no válido o caducado."

    old_password_still_works = client.post(
        "/api/v1/auth/token",
        data={"username": "user@example.com", "password": _PASSWORD},
    )
    assert old_password_still_works.status_code == 200


def test_mailer_translates_transport_failure_without_exposing_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_PORT", "587")
    monkeypatch.setenv("ATHENA_RECOVERY_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("ATHENA_RECOVERY_PUBLIC_URL", "https://example.com/recover")

    def _fail_smtp(*args, **kwargs):
        del args, kwargs
        raise OSError("simulated transport failure")

    monkeypatch.setattr("app.services.password_recovery_mailer.smtplib.SMTP", _fail_smtp)
    mailer = PasswordRecoveryMailer()
    challenge = PasswordRecoveryChallenge(
        email="user@example.com",
        token="sensitive-token-value-that-must-never-be-exposed-123456",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    with pytest.raises(PasswordRecoveryDeliveryError) as caught:
        mailer.send(challenge)
    assert challenge.token not in str(caught.value)
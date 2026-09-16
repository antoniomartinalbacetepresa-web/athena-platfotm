from __future__ import annotations

import ssl
from datetime import datetime, timezone

import pytest

from app.services.password_recovery_mailer import PasswordRecoveryMailer
from app.services.password_recovery_service import PasswordRecoveryChallenge


def _configure(monkeypatch, *, starttls: str = "true") -> None:
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_PORT", "587")
    monkeypatch.setenv("ATHENA_RECOVERY_FROM_EMAIL", "recovery@example.test")
    monkeypatch.setenv("ATHENA_RECOVERY_PUBLIC_URL", "https://example.test/recover")
    monkeypatch.setenv("ATHENA_RECOVERY_SMTP_STARTTLS", starttls)


def test_recovery_mailer_rejects_plaintext_smtp(monkeypatch) -> None:
    _configure(monkeypatch, starttls="false")

    with pytest.raises(RuntimeError, match="no puede desactivarse"):
        PasswordRecoveryMailer()


def test_recovery_mailer_upgrades_modern_tls_before_sending(monkeypatch) -> None:
    _configure(monkeypatch)
    events: list[str] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "smtp.example.test"
            assert port == 587
            assert timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def ehlo(self) -> None:
            events.append("ehlo")

        def starttls(self, *, context) -> None:
            assert context is not None
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname is True
            assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
            events.append("starttls")

        def login(self, username: str, password: str) -> None:
            events.append("login")

        def send_message(self, message) -> None:
            assert "token=secret-recovery-token-1234567890" in message.get_content()
            events.append("send")

    monkeypatch.setattr("app.services.password_recovery_mailer.smtplib.SMTP", FakeSMTP)
    mailer = PasswordRecoveryMailer()
    mailer.send(
        PasswordRecoveryChallenge(
            email="owner@example.test",
            token="secret-recovery-token-1234567890",
            expires_at=datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc),
        )
    )

    assert events == ["ehlo", "starttls", "ehlo", "send"]

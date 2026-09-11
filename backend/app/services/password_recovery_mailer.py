from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

from app.services.password_recovery_service import PasswordRecoveryChallenge


class PasswordRecoveryMailer:
    """SMTP delivery for password-recovery links.

    The channel is fail-closed: no development fallback prints or returns the
    recovery token. Production must explicitly configure SMTP and the public
    recovery URL.
    """

    def __init__(self) -> None:
        self._host = str(os.getenv("ATHENA_RECOVERY_SMTP_HOST") or "").strip()
        self._port = int(str(os.getenv("ATHENA_RECOVERY_SMTP_PORT") or "587").strip())
        self._username = str(os.getenv("ATHENA_RECOVERY_SMTP_USERNAME") or "").strip()
        self._password = str(os.getenv("ATHENA_RECOVERY_SMTP_PASSWORD") or "")
        self._sender = str(os.getenv("ATHENA_RECOVERY_FROM_EMAIL") or "").strip()
        self._base_url = str(os.getenv("ATHENA_RECOVERY_PUBLIC_URL") or "").strip()
        self._use_starttls = str(os.getenv("ATHENA_RECOVERY_SMTP_STARTTLS") or "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        if not self._host or not self._sender or not self._base_url:
            raise RuntimeError("El canal de recuperación SMTP no está configurado.")
        if not self._base_url.lower().startswith("https://"):
            raise RuntimeError("ATHENA_RECOVERY_PUBLIC_URL debe usar HTTPS.")
        if self._port <= 0 or self._port > 65535:
            raise RuntimeError("ATHENA_RECOVERY_SMTP_PORT no es válido.")

    def send(self, challenge: PasswordRecoveryChallenge) -> None:
        separator = "&" if "?" in self._base_url else "?"
        recovery_url = f"{self._base_url}{separator}{urlencode({'token': challenge.token})}"
        message = EmailMessage()
        message["Subject"] = "Recuperación de acceso a ATHENA TYCHE"
        message["From"] = self._sender
        message["To"] = challenge.email
        message.set_content(
            "Se ha solicitado restablecer tu contraseña de ATHENA TYCHE.\n\n"
            f"Enlace de recuperación: {recovery_url}\n\n"
            f"El enlace caduca a las {challenge.expires_at.isoformat()}.\n"
            "Si no solicitaste este cambio, ignora este mensaje."
        )
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            smtp.ehlo()
            if self._use_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(message)

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash

from app.repositories.auth_security_repository import AuthSecurityRepository
from app.repositories.password_recovery_repository import PasswordRecoveryRepository
from app.repositories.user_account_repository import UserAccountRepository


@dataclass(frozen=True)
class PasswordRecoveryChallenge:
    email: str
    token: str
    expires_at: datetime


class PasswordRecoveryService:
    TOKEN_TTL_MINUTES = 30
    MINIMUM_PASSWORD_LENGTH = 12

    def __init__(
        self,
        *,
        account_repository: UserAccountRepository | None = None,
        recovery_repository: PasswordRecoveryRepository | None = None,
        security_repository: AuthSecurityRepository | None = None,
    ) -> None:
        self._accounts = account_repository or UserAccountRepository()
        self._recovery = recovery_repository or PasswordRecoveryRepository()
        self._security = security_repository or AuthSecurityRepository()
        self._password_hash = PasswordHash.recommended()

    def request(self, *, email: str) -> PasswordRecoveryChallenge | None:
        raw_token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.TOKEN_TTL_MINUTES)
        try:
            account = self._accounts.get_by_email(email)
        except ValueError:
            account = None
        if account is None or int(account.get("is_active") or 0) != 1:
            return None
        self._recovery.create(
            token_hash=token_hash,
            user_id=int(account["id"]),
            expires_at=expires_at,
        )
        return PasswordRecoveryChallenge(
            email=str(account["email"]),
            token=raw_token,
            expires_at=expires_at,
        )

    def reset(self, *, token: str, new_password: str) -> bool:
        normalized_token = str(token or "").strip()
        if len(normalized_token) < 32:
            return False
        user_id = self._recovery.consume(token_hash=self._token_hash(normalized_token))
        if user_id is None:
            return False
        account = self._accounts.get_by_id(int(user_id))
        if account is None or int(account.get("is_active") or 0) != 1:
            return False
        password = self._validate_password(new_password)
        stored_hash = str(account.get("password_hash") or "")
        if stored_hash and self._password_hash.verify(password, stored_hash):
            raise ValueError("La nueva contraseña debe ser diferente de la actual.")
        password_hash = self._password_hash.hash(password)
        if not self._accounts.update_password_hash(
            user_id=int(user_id),
            password_hash=password_hash,
        ):
            return False
        self._security.revoke_all_sessions(user_id=int(user_id))
        self._recovery.invalidate_for_user(user_id=int(user_id))
        return True

    def invalidate(self, *, user_id: int) -> None:
        self._recovery.invalidate_for_user(user_id=int(user_id))

    def _token_hash(self, token: str) -> str:
        return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

    def _validate_password(self, password: str) -> str:
        value = str(password or "")
        if len(value) < self.MINIMUM_PASSWORD_LENGTH:
            raise ValueError(
                f"La contraseña debe tener al menos {self.MINIMUM_PASSWORD_LENGTH} caracteres."
            )
        if len(value) > 256:
            raise ValueError("La contraseña supera el máximo permitido.")
        if value.strip() != value:
            raise ValueError("La contraseña no puede empezar ni terminar con espacios.")
        return value

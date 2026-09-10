from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.repositories.user_account_repository import UserAccountRepository


class AuthService:
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    MINIMUM_SECRET_BYTES = 32
    MINIMUM_PASSWORD_LENGTH = 12

    def __init__(
        self,
        *,
        repository: UserAccountRepository | None = None,
        secret_key: str | None = None,
    ) -> None:
        # Validate signing configuration before touching persistent auth state.
        self._secret_key = self._load_secret(secret_key)
        self._repository = repository or UserAccountRepository()
        self._password_hash = PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash("athena-dummy-password-not-a-user")

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_password = self._validate_password(password)
        password_hash = self._password_hash.hash(normalized_password)
        account = self._repository.create(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        return self._public_account(account)

    def authenticate(self, *, email: str, password: str) -> dict[str, Any] | None:
        try:
            account = self._repository.get_by_email(email)
        except ValueError:
            account = None
        if account is None:
            self._password_hash.verify(password, self._dummy_hash)
            return None
        stored_hash = str(account.get("password_hash") or "")
        if not stored_hash or not self._password_hash.verify(password, stored_hash):
            return None
        if int(account.get("is_active") or 0) != 1:
            return None
        return self._public_account(account)

    def create_access_token(self, *, user_id: int, email: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(int(user_id)),
            "email": str(email).strip().lower(),
            "iat": now,
            "exp": now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES),
            "iss": "athena-tyche",
            "aud": "athena-tyche-app",
        }
        return jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM)

    def account_from_token(self, token: str) -> dict[str, Any] | None:
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                issuer="athena-tyche",
                audience="athena-tyche-app",
                options={"require": ["sub", "iat", "exp", "iss", "aud"]},
            )
            subject = str(payload.get("sub") or "")
            if not subject.isdigit() or int(subject) <= 0:
                return None
            account = self._repository.get_by_id(int(subject))
            if account is None or int(account.get("is_active") or 0) != 1:
                return None
            return self._public_account(account)
        except (InvalidTokenError, ValueError, TypeError):
            return None

    def _public_account(self, account: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(account["id"]),
            "email": str(account["email"]),
            "displayName": account.get("display_name"),
            "isActive": int(account.get("is_active") or 0) == 1,
            "createdAt": str(account["created_at"]),
            "updatedAt": str(account["updated_at"]),
        }

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

    def _load_secret(self, override: str | None) -> str:
        value = override if override is not None else os.getenv("ATHENA_AUTH_SECRET")
        normalized = str(value or "").strip()
        if len(normalized.encode("utf-8")) < self.MINIMUM_SECRET_BYTES:
            raise RuntimeError(
                "ATHENA_AUTH_SECRET debe contener al menos 32 bytes y no puede usar un valor por defecto."
            )
        return normalized

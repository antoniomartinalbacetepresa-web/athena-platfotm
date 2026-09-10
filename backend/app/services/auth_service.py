from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.repositories.auth_security_repository import AuthSecurityRepository
from app.repositories.user_account_repository import UserAccountRepository


class AuthService:
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    MINIMUM_SECRET_BYTES = 32
    MINIMUM_PASSWORD_LENGTH = 12
    LOGIN_ATTEMPT_LIMIT = 8
    LOGIN_WINDOW_SECONDS = 300

    def __init__(self, *, repository: UserAccountRepository | None = None, security_repository: AuthSecurityRepository | None = None, secret_key: str | None = None) -> None:
        self._secret_key = self._load_secret(secret_key)
        self._repository = repository or UserAccountRepository()
        self._security_repository = security_repository or AuthSecurityRepository()
        self._password_hash = PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash("athena-dummy-password-not-a-user")

    def register(self, *, email: str, password: str, display_name: str | None = None) -> dict[str, Any]:
        normalized_password = self._validate_password(password)
        password_hash = self._password_hash.hash(normalized_password)
        account = self._repository.create(email=email, password_hash=password_hash, display_name=display_name)
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

    def login_rate_key(self, *, email: str, client_id: str) -> str:
        normalized_email = str(email or "").strip().lower()
        normalized_client = str(client_id or "unknown").strip().lower() or "unknown"
        digest = hashlib.sha256(f"{normalized_client}|{normalized_email}".encode("utf-8")).hexdigest()
        return f"auth-login:{digest}"

    def consume_login_attempt(self, *, rate_key: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())
        window_epoch = epoch - (epoch % self.LOGIN_WINDOW_SECONDS)
        window_start = datetime.fromtimestamp(window_epoch, tz=timezone.utc)
        return self._security_repository.consume_login_attempt(key=rate_key, window_started_at=window_start, limit=self.LOGIN_ATTEMPT_LIMIT)

    def clear_login_attempts(self, *, rate_key: str) -> None:
        self._security_repository.clear_login_attempts(key=rate_key)

    def create_access_token(self, *, user_id: int, email: str) -> str:
        now = datetime.now(timezone.utc)
        session_version = self._security_repository.current_session_version(user_id=int(user_id))
        payload = {
            "sub": str(int(user_id)),
            "email": str(email).strip().lower(),
            "jti": uuid.uuid4().hex,
            "sv": session_version,
            "iat": now,
            "exp": now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES),
            "iss": "athena-tyche",
            "aud": "athena-tyche-app",
        }
        return jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM)

    def account_from_token(self, token: str) -> dict[str, Any] | None:
        payload = self._decode_token(token)
        if payload is None:
            return None
        subject = str(payload.get("sub") or "")
        jti = str(payload.get("jti") or "")
        session_version = payload.get("sv")
        if not subject.isdigit() or int(subject) <= 0 or not jti or not isinstance(session_version, int) or session_version <= 0:
            return None
        user_id = int(subject)
        if self._security_repository.is_token_revoked(jti=jti):
            return None
        if self._security_repository.current_session_version(user_id=user_id) != session_version:
            return None
        account = self._repository.get_by_id(user_id)
        if account is None or int(account.get("is_active") or 0) != 1:
            return None
        return self._public_account(account)

    def revoke_access_token(self, token: str) -> bool:
        payload = self._decode_token(token)
        if payload is None:
            return False
        subject = str(payload.get("sub") or "")
        jti = str(payload.get("jti") or "")
        exp = payload.get("exp")
        if not subject.isdigit() or int(subject) <= 0 or not jti:
            return False
        try:
            expires_at = datetime.fromtimestamp(float(exp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return False
        self._security_repository.revoke_token(jti=jti, user_id=int(subject), expires_at=expires_at)
        return True

    def revoke_all_sessions(self, *, user_id: int) -> int:
        return self._security_repository.revoke_all_sessions(user_id=int(user_id))

    def _decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                issuer="athena-tyche",
                audience="athena-tyche-app",
                options={"require": ["sub", "jti", "sv", "iat", "exp", "iss", "aud"]},
            )
            return payload if isinstance(payload, dict) else None
        except (InvalidTokenError, ValueError, TypeError):
            return None

    def _public_account(self, account: dict[str, Any]) -> dict[str, Any]:
        return {"id": int(account["id"]), "email": str(account["email"]), "displayName": account.get("display_name"), "isActive": int(account.get("is_active") or 0) == 1, "createdAt": str(account["created_at"]), "updatedAt": str(account["updated_at"])}

    def _validate_password(self, password: str) -> str:
        value = str(password or "")
        if len(value) < self.MINIMUM_PASSWORD_LENGTH:
            raise ValueError(f"La contraseña debe tener al menos {self.MINIMUM_PASSWORD_LENGTH} caracteres.")
        if len(value) > 256:
            raise ValueError("La contraseña supera el máximo permitido.")
        if value.strip() != value:
            raise ValueError("La contraseña no puede empezar ni terminar con espacios.")
        return value

    def _load_secret(self, override: str | None) -> str:
        value = override if override is not None else os.getenv("ATHENA_AUTH_SECRET")
        normalized = str(value or "").strip()
        if len(normalized.encode("utf-8")) < self.MINIMUM_SECRET_BYTES:
            raise RuntimeError("ATHENA_AUTH_SECRET debe contener al menos 32 bytes y no puede usar un valor por defecto.")
        return normalized

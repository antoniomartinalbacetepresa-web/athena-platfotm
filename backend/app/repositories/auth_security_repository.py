from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class AuthSecurityRepository:
    """Persistent auth-security state shared by all backend processes.

    Stores revoked JWT identifiers, per-user session versions and fixed-window
    login counters. No plaintext password, bearer token, or secret key is ever
    persisted here.
    """

    _REVOKED_TABLE = "athena_revoked_auth_tokens"
    _RATE_TABLE = "athena_auth_rate_limits"
    _SESSION_TABLE = "athena_auth_user_sessions"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_tables()

    def revoke_token(self, *, jti: str, user_id: int, expires_at: datetime) -> None:
        normalized_jti = self._required(jti, "jti")
        if user_id <= 0:
            raise ValueError("user_id debe ser positivo.")
        expiry = self._aware(expires_at, "expires_at")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {self._REVOKED_TABLE} (
                    jti, user_id, expires_at, revoked_at
                ) VALUES (?, ?, ?, ?)
                """,
                (normalized_jti, int(user_id), expiry.isoformat(), now),
            )
            connection.execute(
                f"DELETE FROM {self._REVOKED_TABLE} WHERE expires_at < ?",
                (now,),
            )

    def is_token_revoked(self, *, jti: str) -> bool:
        normalized_jti = self._required(jti, "jti")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT 1
                FROM {self._REVOKED_TABLE}
                WHERE jti = ? AND expires_at >= ?
                LIMIT 1
                """,
                (normalized_jti, now),
            ).fetchone()
        return row is not None

    def current_session_version(self, *, user_id: int) -> int:
        if user_id <= 0:
            raise ValueError("user_id debe ser positivo.")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {self._SESSION_TABLE} (
                    user_id, session_version, updated_at
                ) VALUES (?, 1, ?)
                """,
                (int(user_id), now),
            )
            row = connection.execute(
                f"""
                SELECT session_version
                FROM {self._SESSION_TABLE}
                WHERE user_id = ?
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo resolver la versión de sesión.")
        return int(row["session_version"])

    def revoke_all_sessions(self, *, user_id: int) -> int:
        if user_id <= 0:
            raise ValueError("user_id debe ser positivo.")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT OR IGNORE INTO {self._SESSION_TABLE} (
                    user_id, session_version, updated_at
                ) VALUES (?, 1, ?)
                """,
                (int(user_id), now),
            )
            connection.execute(
                f"""
                UPDATE {self._SESSION_TABLE}
                SET session_version = session_version + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (now, int(user_id)),
            )
            row = connection.execute(
                f"""
                SELECT session_version
                FROM {self._SESSION_TABLE}
                WHERE user_id = ?
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo revocar las sesiones del usuario.")
        return int(row["session_version"])

    def consume_login_attempt(
        self,
        *,
        key: str,
        window_started_at: datetime,
        limit: int,
    ) -> dict[str, Any]:
        normalized_key = self._required(key, "key")
        if limit <= 0:
            raise ValueError("limit debe ser positivo.")
        window = self._aware(window_started_at, "window_started_at").isoformat()
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT attempts, window_started_at
                FROM {self._RATE_TABLE}
                WHERE rate_key = ?
                LIMIT 1
                """,
                (normalized_key,),
            ).fetchone()
            if row is None or str(row["window_started_at"]) != window:
                attempts = 1
                connection.execute(
                    f"""
                    INSERT INTO {self._RATE_TABLE} (
                        rate_key, window_started_at, attempts, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(rate_key) DO UPDATE SET
                        window_started_at = excluded.window_started_at,
                        attempts = excluded.attempts,
                        updated_at = excluded.updated_at
                    """,
                    (normalized_key, window, attempts, now),
                )
            else:
                attempts = int(row["attempts"]) + 1
                connection.execute(
                    f"""
                    UPDATE {self._RATE_TABLE}
                    SET attempts = ?, updated_at = ?
                    WHERE rate_key = ?
                    """,
                    (attempts, now, normalized_key),
                )
        return {
            "attempts": attempts,
            "limit": int(limit),
            "allowed": attempts <= limit,
            "remaining": max(0, limit - attempts),
            "windowStartedAt": window,
        }

    def clear_login_attempts(self, *, key: str) -> None:
        normalized_key = self._required(key, "key")
        with self._database.connect() as connection:
            connection.execute(
                f"DELETE FROM {self._RATE_TABLE} WHERE rate_key = ?",
                (normalized_key,),
            )

    def _ensure_tables(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._REVOKED_TABLE} (
                    jti TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_athena_revoked_auth_tokens_expiry
                ON {self._REVOKED_TABLE} (expires_at);

                CREATE TABLE IF NOT EXISTS {self._RATE_TABLE} (
                    rate_key TEXT PRIMARY KEY,
                    window_started_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL CHECK (attempts >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS {self._SESSION_TABLE} (
                    user_id INTEGER PRIMARY KEY,
                    session_version INTEGER NOT NULL DEFAULT 1
                        CHECK (session_version > 0),
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES athena_user_accounts(id)
                        ON DELETE CASCADE
                );
                """
            )

    def _required(self, value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _aware(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

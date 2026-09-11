from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class PasswordRecoveryRepository:
    """Persistent one-time password-recovery challenges.

    Only a SHA-256 digest of the bearer recovery token is persisted. Raw
    recovery tokens must exist only long enough to be delivered to the user.
    """

    _TABLE = "athena_password_recovery_tokens"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_table()

    def create(
        self,
        *,
        token_hash: str,
        user_id: int,
        expires_at: datetime,
    ) -> None:
        normalized_hash = self._required(token_hash, "token_hash")
        if int(user_id) <= 0:
            raise ValueError("user_id debe ser positivo.")
        expiry = self._aware(expires_at, "expires_at")
        now = datetime.now(timezone.utc)
        if expiry <= now:
            raise ValueError("expires_at debe estar en el futuro.")
        with self._database.connect() as connection:
            connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET consumed_at = ?
                WHERE user_id = ? AND consumed_at IS NULL
                """,
                (now.isoformat(), int(user_id)),
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    token_hash, user_id, expires_at, created_at, consumed_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    normalized_hash,
                    int(user_id),
                    expiry.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.execute(
                f"DELETE FROM {self._TABLE} WHERE expires_at < ?",
                ((now.replace(microsecond=0)).isoformat(),),
            )

    def consume(self, *, token_hash: str) -> int | None:
        normalized_hash = self._required(token_hash, "token_hash")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT user_id
                FROM {self._TABLE}
                WHERE token_hash = ?
                  AND consumed_at IS NULL
                  AND expires_at >= ?
                LIMIT 1
                """,
                (normalized_hash, now),
            ).fetchone()
            if row is None:
                return None
            cursor = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET consumed_at = ?
                WHERE token_hash = ?
                  AND consumed_at IS NULL
                  AND expires_at >= ?
                """,
                (now, normalized_hash, now),
            )
            if int(cursor.rowcount or 0) != 1:
                return None
            return int(row["user_id"])

    def invalidate_for_user(self, *, user_id: int) -> None:
        if int(user_id) <= 0:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET consumed_at = ?
                WHERE user_id = ? AND consumed_at IS NULL
                """,
                (now, int(user_id)),
            )

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES athena_user_accounts(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_athena_password_recovery_user
                ON {self._TABLE} (user_id, consumed_at, expires_at);
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

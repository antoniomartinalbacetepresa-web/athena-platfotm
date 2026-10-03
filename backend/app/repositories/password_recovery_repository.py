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
    _ACCOUNT_TABLE = "athena_user_accounts"
    _SESSION_TABLE = "athena_auth_user_sessions"

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

    def valid_user_id(self, *, token_hash: str) -> int | None:
        """Resolve a live challenge without consuming it.

        Password policy and account-state checks can therefore complete before
        the one-time token is irreversibly consumed. The subsequent atomic reset
        remains the authority that decides which concurrent reset, if any, wins.
        """

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
        return None if row is None else int(row["user_id"])

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

    def complete_password_reset(
        self,
        *,
        token_hash: str,
        user_id: int,
        password_hash: str,
    ) -> bool:
        """Commit recovery consumption, password rotation and revocation atomically.

        All security state touched by a successful reset lives in the canonical
        SQLite database. Acquiring the write lock before re-validating the token
        prevents two concurrent resets from both succeeding. Any SQL failure
        rolls the whole transaction back, so a recoverable infrastructure error
        cannot leave the one-time challenge consumed while the old password or
        old session version remains active.
        """

        normalized_hash = self._required(token_hash, "token_hash")
        normalized_password_hash = self._required(password_hash, "password_hash")
        normalized_user_id = int(user_id)
        if normalized_user_id <= 0:
            raise ValueError("user_id debe ser positivo.")
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT user_id
                FROM {self._TABLE}
                WHERE token_hash = ?
                  AND user_id = ?
                  AND consumed_at IS NULL
                  AND expires_at >= ?
                LIMIT 1
                """,
                (normalized_hash, normalized_user_id, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False

            consumed = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET consumed_at = ?
                WHERE token_hash = ?
                  AND user_id = ?
                  AND consumed_at IS NULL
                  AND expires_at >= ?
                """,
                (now, normalized_hash, normalized_user_id, now),
            )
            if int(consumed.rowcount or 0) != 1:
                connection.rollback()
                return False

            password_updated = connection.execute(
                f"""
                UPDATE {self._ACCOUNT_TABLE}
                SET password_hash = ?, updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (normalized_password_hash, now, normalized_user_id),
            )
            if int(password_updated.rowcount or 0) != 1:
                connection.rollback()
                return False

            connection.execute(
                f"""
                INSERT OR IGNORE INTO {self._SESSION_TABLE} (
                    user_id, session_version, updated_at
                ) VALUES (?, 1, ?)
                """,
                (normalized_user_id, now),
            )
            session_revoked = connection.execute(
                f"""
                UPDATE {self._SESSION_TABLE}
                SET session_version = session_version + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (now, normalized_user_id),
            )
            if int(session_revoked.rowcount or 0) != 1:
                connection.rollback()
                return False

            connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET consumed_at = ?
                WHERE user_id = ? AND consumed_at IS NULL
                """,
                (now, normalized_user_id),
            )
            connection.commit()
        return True

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

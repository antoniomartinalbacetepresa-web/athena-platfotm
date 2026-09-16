from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class UserAccountRepository:
    """Minimal persisted user identity store.

    Passwords are never accepted or stored here; only externally generated
    password hashes may be persisted. Profile/preferences are deliberately kept
    out of this table until their privacy and encryption contract is defined.
    """

    _TABLE = "athena_user_accounts"
    _PROFILE_TABLE = "athena_user_profile_preferences"
    _PORTFOLIO_TABLE = "athena_user_portfolio_positions"
    _SESSION_TABLE = "athena_auth_user_sessions"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_table()

    def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_email = self._email(email)
        normalized_hash = self._required(password_hash, "password_hash")
        normalized_name = str(display_name or "").strip() or None
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.connect() as connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {self._TABLE} (
                        email,
                        password_hash,
                        display_name,
                        is_active,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (
                        normalized_email,
                        normalized_hash,
                        normalized_name,
                        now,
                        now,
                    ),
                )
                user_id = int(cursor.lastrowid)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError("Ya existe una cuenta para este email.") from exc
            raise
        user = self.get_by_id(user_id)
        if user is None:
            raise RuntimeError("La cuenta recién creada no pudo recuperarse.")
        return user

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        normalized_email = self._email(email)
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE email = ? LIMIT 1",
                (normalized_email,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        if user_id <= 0:
            return None
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {self._TABLE} WHERE id = ? LIMIT 1",
                (int(user_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_password_hash(self, *, user_id: int, password_hash: str) -> bool:
        if int(user_id) <= 0:
            return False
        normalized_hash = self._required(password_hash, "password_hash")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET password_hash = ?, updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (normalized_hash, now, int(user_id)),
            )
        return int(cursor.rowcount or 0) == 1

    def update_password_hash_and_rotate_sessions(
        self,
        *,
        user_id: int,
        password_hash: str,
    ) -> bool:
        """Rotate the credential and session version in one transaction.

        A password change is not secure if the new credential commits while old
        bearer sessions remain valid. The account hash and the canonical session
        version therefore share one SQLite write transaction: any failure in the
        session rotation rolls the password update back as well.
        """
        normalized_user_id = int(user_id)
        if normalized_user_id <= 0:
            return False
        normalized_hash = self._required(password_hash, "password_hash")
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            password_updated = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET password_hash = ?, updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (normalized_hash, now, normalized_user_id),
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
            session_rotated = connection.execute(
                f"""
                UPDATE {self._SESSION_TABLE}
                SET session_version = session_version + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (now, normalized_user_id),
            )
            if int(session_rotated.rowcount or 0) != 1:
                connection.rollback()
                return False
            connection.commit()
        return True

    def deactivate(self, *, user_id: int) -> bool:
        """Deactivate one account without deleting audit-relevant identity data."""
        if int(user_id) <= 0:
            return False
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET is_active = 0, updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (now, int(user_id)),
            )
        return int(cursor.rowcount or 0) == 1

    def close_and_anonymize(
        self,
        *,
        user_id: int,
        replacement_password_hash: str,
    ) -> bool:
        """Close one account and purge mutable owner-scoped personal state atomically.

        Direct identity PII is removed while the stable numeric id is retained for
        referential/audit integrity. If profile or current-position tables exist,
        their owner rows are deleted in the same transaction. Append-only evidence
        stores are intentionally not rewritten here because doing so would destroy
        their integrity chain; their retention is a separate governed contract.
        """
        if int(user_id) <= 0:
            return False
        normalized_hash = self._required(
            replacement_password_hash, "replacement_password_hash"
        )
        anonymized_email = f"closed-{int(user_id)}@account.invalid"
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                f"SELECT is_active FROM {self._TABLE} WHERE id = ? LIMIT 1",
                (int(user_id),),
            ).fetchone()
            if active is None or int(active["is_active"] or 0) != 1:
                connection.rollback()
                return False

            for table_name in (self._PROFILE_TABLE, self._PORTFOLIO_TABLE):
                if self._table_exists(connection, table_name):
                    connection.execute(
                        f"DELETE FROM {table_name} WHERE owner_user_id = ?",
                        (int(user_id),),
                    )

            cursor = connection.execute(
                f"""
                UPDATE {self._TABLE}
                SET email = ?,
                    password_hash = ?,
                    display_name = NULL,
                    is_active = 0,
                    updated_at = ?
                WHERE id = ? AND is_active = 1
                """,
                (anonymized_email, normalized_hash, now, int(user_id)),
            )
            if int(cursor.rowcount or 0) != 1:
                connection.rollback()
                return False
            connection.commit()
        return True

    @staticmethod
    def _table_exists(connection: Any, table_name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_athena_user_accounts_active
                ON {self._TABLE} (is_active, id);
                """
            )

    def _email(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) > 254 or _EMAIL_RE.fullmatch(normalized) is None:
            raise ValueError("Email no válido.")
        return normalized

    def _required(self, value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

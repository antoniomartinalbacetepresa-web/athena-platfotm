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

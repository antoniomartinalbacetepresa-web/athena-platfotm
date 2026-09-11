from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.database.athena_database import AthenaDatabase


class UserPortfolioRepository:
    """Persist the minimal declared holdings of one authenticated ATHENA user.

    Ownership is always supplied by trusted backend code. The repository never
    accepts email addresses or client-provided ownership metadata. Cost basis,
    total capital and free-form notes are intentionally excluded until ATHENA
    has an approved encryption/privacy contract for sensitive portfolio data.
    """

    _TABLE = "athena_user_portfolio_positions"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._database.initialize()
        self._ensure_table()

    def list_for_owner(self, owner_user_id: int) -> list[dict[str, Any]]:
        owner_id = self._owner_id(owner_user_id)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, symbol, exchange, quantity, created_at, updated_at
                FROM {self._TABLE}
                WHERE owner_user_id = ?
                ORDER BY symbol ASC, exchange ASC, id ASC
                """,
                (owner_id,),
            ).fetchall()
        return [self._public_row(dict(row)) for row in rows]

    def upsert(
        self,
        *,
        owner_user_id: int,
        symbol: str,
        exchange: str | None,
        quantity: float,
    ) -> dict[str, Any]:
        owner_id = self._owner_id(owner_user_id)
        normalized_symbol = self._symbol(symbol)
        normalized_exchange = self._exchange(exchange)
        normalized_quantity = self._quantity(quantity)
        now = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    owner_user_id, symbol, exchange, quantity, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, symbol, exchange)
                DO UPDATE SET
                    quantity = excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    normalized_symbol,
                    normalized_exchange,
                    normalized_quantity,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                f"""
                SELECT id, symbol, exchange, quantity, created_at, updated_at
                FROM {self._TABLE}
                WHERE owner_user_id = ? AND symbol = ? AND exchange = ?
                LIMIT 1
                """,
                (owner_id, normalized_symbol, normalized_exchange),
            ).fetchone()

        if row is None:
            raise RuntimeError("La posición no pudo recuperarse tras persistirla.")
        return self._public_row(dict(row))

    def delete_for_owner(self, *, owner_user_id: int, position_id: int) -> bool:
        owner_id = self._owner_id(owner_user_id)
        if isinstance(position_id, bool) or not isinstance(position_id, int) or position_id <= 0:
            return False
        with self._database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {self._TABLE} WHERE id = ? AND owner_user_id = ?",
                (position_id, owner_id),
            )
        return cursor.rowcount == 1

    def _ensure_table(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id)
                        REFERENCES athena_user_accounts(id)
                        ON DELETE CASCADE,
                    UNIQUE (owner_user_id, symbol, exchange)
                );

                CREATE INDEX IF NOT EXISTS idx_athena_user_portfolio_owner
                ON {self._TABLE} (owner_user_id, symbol, exchange);
                """
            )

    @staticmethod
    def _owner_id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("owner_user_id interno no válido.")
        return value

    @staticmethod
    def _symbol(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized or len(normalized) > 32:
            raise ValueError("symbol no válido.")
        return normalized

    @staticmethod
    def _exchange(value: str | None) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) > 32:
            raise ValueError("exchange no válido.")
        return normalized

    @staticmethod
    def _quantity(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("quantity debe ser numérica y positiva.")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError("quantity debe ser un número finito positivo.")
        if normalized <= 0 or normalized > 1_000_000_000_000:
            raise ValueError("quantity debe ser positiva y estar dentro del límite operativo.")
        return normalized

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "symbol": str(row["symbol"]),
            "exchange": str(row["exchange"]) or None,
            "quantity": float(row["quantity"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

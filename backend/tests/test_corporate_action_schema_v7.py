from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.database.athena_database_v6 import AthenaDatabase as AthenaDatabaseV6


def _insert_instrument(connection: sqlite3.Connection) -> int:
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (symbol, company_name, exchange_short_name)
        VALUES ('AAPL', 'Apple Inc.', 'NASDAQ')
        """
    ).lastrowid
    assert instrument_id is not None
    return int(instrument_id)


def test_v7_storage_boundary_rejects_invalid_currency(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "v7.db")
    database.initialize()

    with database.connect() as connection:
        instrument_id = _insert_instrument(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO corporate_actions (
                    instrument_id, action_type, effective_at, cash_amount,
                    currency, source_provider, retrieved_at
                ) VALUES (?, 'dividend', ?, 0.25, 'USDT', 'manual', ?)
                """,
                (
                    instrument_id,
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-02T00:00:00+00:00",
                ),
            )

        count = connection.execute(
            "SELECT COUNT(*) AS count FROM corporate_actions"
        ).fetchone()

    assert count is not None
    assert count["count"] == 0


def test_v7_migration_fails_closed_on_invalid_legacy_currency(tmp_path: Path) -> None:
    database_path = tmp_path / "invalid-v6.db"
    legacy = AthenaDatabaseV6(database_path)
    legacy.initialize()

    with legacy.connect() as connection:
        instrument_id = _insert_instrument(connection)
        connection.execute(
            """
            INSERT INTO corporate_actions (
                instrument_id, action_type, effective_at, cash_amount,
                currency, source_provider, retrieved_at
            ) VALUES (?, 'dividend', ?, 0.25, 'USDT', 'legacy', ?)
            """,
            (
                instrument_id,
                "2026-09-01T00:00:00+00:00",
                "2026-09-02T00:00:00+00:00",
            ),
        )

    with pytest.raises(RuntimeError, match="currency inválida"):
        AthenaDatabase(database_path).initialize()

    with legacy.connect() as connection:
        row = connection.execute(
            "SELECT currency FROM corporate_actions"
        ).fetchone()

    assert row is not None
    assert row["currency"] == "USDT"

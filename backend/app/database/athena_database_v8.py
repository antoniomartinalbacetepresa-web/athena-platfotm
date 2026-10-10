from __future__ import annotations

import sqlite3

from app.database.athena_database_v7 import AthenaConnection, AthenaDatabase as _V7AthenaDatabase


class AthenaDatabase(_V7AthenaDatabase):
    """Schema v8 adds immutable PIT issuer financial periods for dividend coverage."""

    SCHEMA_VERSION = 8

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        super()._create_schema(connection)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS financial_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                currency TEXT NOT NULL CHECK (
                    length(currency) = 3 AND currency GLOB '[A-Z][A-Z][A-Z]'
                ),
                net_income REAL,
                free_cash_flow REAL,
                source_provider TEXT NOT NULL,
                source_timestamp TEXT,
                retrieved_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE CASCADE,
                CHECK (period_start <= period_end),
                CHECK (net_income IS NOT NULL OR free_cash_flow IS NOT NULL),
                UNIQUE (
                    instrument_id, period_start, period_end, currency,
                    net_income, free_cash_flow, source_provider, retrieved_at
                )
            );

            CREATE INDEX IF NOT EXISTS idx_financial_periods_pit
            ON financial_periods (instrument_id, retrieved_at, period_end);
            """
        )


__all__ = ["AthenaConnection", "AthenaDatabase"]

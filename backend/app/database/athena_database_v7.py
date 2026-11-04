from __future__ import annotations

import sqlite3

from app.database.athena_database_v6 import (
    AthenaConnection,
    AthenaDatabase as _V6AthenaDatabase,
)


class AthenaDatabase(_V6AthenaDatabase):
    """Schema v7 enforces the corporate-action currency contract in SQLite.

    Repository validation is not a sufficient integrity boundary because
    migrations, maintenance tooling, or future ingestion paths can write to
    SQLite directly. v7 therefore rejects non-ISO-shaped currency values at
    the durable storage boundary and fails closed when legacy rows violate the
    contract instead of silently rewriting historical PIT evidence.
    """

    SCHEMA_VERSION = 7

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        super()._create_schema(connection)
        self._migrate_corporate_actions_currency_constraint(connection)

    def _migrate_corporate_actions_currency_constraint(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        table_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='corporate_actions'"
        ).fetchone()
        if table_sql_row is None:
            raise RuntimeError("corporate_actions no existe durante la migración v7.")

        table_sql = str(table_sql_row["sql"] or "")
        if "currency GLOB '[A-Z][A-Z][A-Z]'" in table_sql:
            return

        invalid = connection.execute(
            """
            SELECT id, currency
            FROM corporate_actions
            WHERE currency IS NOT NULL
              AND (
                  length(currency) != 3
                  OR currency NOT GLOB '[A-Z][A-Z][A-Z]'
              )
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if invalid is not None:
            raise RuntimeError(
                "La migración v7 rechaza corporate actions históricas con "
                f"currency inválida (id={invalid['id']})."
            )

        connection.executescript(
            """
            ALTER TABLE corporate_actions RENAME TO corporate_actions_v6;

            CREATE TABLE corporate_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                action_type TEXT NOT NULL
                    CHECK (action_type IN ('dividend', 'split')),
                effective_at TEXT NOT NULL,
                cash_amount REAL,
                split_ratio REAL,
                currency TEXT CHECK (
                    currency IS NULL OR (
                        length(currency) = 3
                        AND currency GLOB '[A-Z][A-Z][A-Z]'
                    )
                ),
                event_identity TEXT GENERATED ALWAYS AS (
                    action_type || '|' ||
                    COALESCE(CAST(cash_amount AS TEXT), '') || '|' ||
                    COALESCE(CAST(split_ratio AS TEXT), '') || '|' ||
                    COALESCE(currency, '')
                ) STORED,
                source_provider TEXT NOT NULL,
                source_timestamp TEXT,
                retrieved_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instrument_id)
                    REFERENCES instruments(id)
                    ON DELETE CASCADE,
                CHECK (
                    (action_type = 'dividend' AND cash_amount > 0
                        AND split_ratio IS NULL)
                    OR
                    (action_type = 'split' AND split_ratio > 0
                        AND cash_amount IS NULL)
                ),
                UNIQUE (
                    instrument_id,
                    action_type,
                    effective_at,
                    event_identity,
                    source_provider,
                    retrieved_at
                )
            );

            INSERT INTO corporate_actions (
                id, instrument_id, action_type, effective_at, cash_amount,
                split_ratio, currency, source_provider, source_timestamp,
                retrieved_at, created_at
            )
            SELECT
                id, instrument_id, action_type, effective_at, cash_amount,
                split_ratio, currency, source_provider, source_timestamp,
                retrieved_at, created_at
            FROM corporate_actions_v6;

            DROP TABLE corporate_actions_v6;

            CREATE INDEX idx_corporate_actions_instrument_effective
            ON corporate_actions (instrument_id, effective_at);

            CREATE INDEX idx_corporate_actions_pit
            ON corporate_actions (instrument_id, retrieved_at, effective_at);
            """
        )


__all__ = ["AthenaConnection", "AthenaDatabase"]

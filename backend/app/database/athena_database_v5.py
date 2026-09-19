from __future__ import annotations

import sqlite3

from app.database.athena_database_legacy import (
    AthenaConnection,
    AthenaDatabase as _LegacyAthenaDatabase,
)


class AthenaDatabase(_LegacyAthenaDatabase):
    """Canonical ATHENA database schema.

    Schema v5 promotes corporate actions from repository-local bootstrap DDL
    into the central database contract. Existing v4 databases are upgraded
    non-destructively because table/index creation is idempotent and preserves
    any PIT rows already ingested by pre-v5 builds.
    """

    SCHEMA_VERSION = 5

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        super()._create_schema(connection)
        self._create_corporate_actions_table(connection)

    def _create_corporate_actions_table(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS corporate_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                action_type TEXT NOT NULL
                    CHECK (action_type IN ('dividend', 'split')),
                effective_at TEXT NOT NULL,
                cash_amount REAL,
                split_ratio REAL,
                currency TEXT,
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
                    source_provider,
                    retrieved_at
                )
            );

            CREATE INDEX IF NOT EXISTS
                idx_corporate_actions_instrument_effective
            ON corporate_actions (
                instrument_id,
                effective_at
            );

            CREATE INDEX IF NOT EXISTS
                idx_corporate_actions_pit
            ON corporate_actions (
                instrument_id,
                retrieved_at,
                effective_at
            );
            """
        )


__all__ = ["AthenaConnection", "AthenaDatabase"]

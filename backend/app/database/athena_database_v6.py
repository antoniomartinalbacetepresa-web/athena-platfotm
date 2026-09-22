from __future__ import annotations

import sqlite3

from app.database.athena_database_v5 import (
    AthenaConnection,
    AthenaDatabase as _V5AthenaDatabase,
)


class AthenaDatabase(_V5AthenaDatabase):
    """Schema v6 gives corporate actions an economic event identity.

    Schema v5 deduplicated only by instrument/type/effective time/provider/
    retrieval time. A provider can legitimately report more than one dividend
    or split of the same type at the same effective timestamp, so that key
    could silently discard a distinct event. v6 keeps idempotency while adding
    the normalized economic payload to the durable identity.
    """

    SCHEMA_VERSION = 6

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        super()._create_schema(connection)
        self._migrate_corporate_actions_identity(connection)

    def _migrate_corporate_actions_identity(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_xinfo(corporate_actions)").fetchall()
        }
        if "event_identity" in columns:
            return

        connection.executescript(
            """
            ALTER TABLE corporate_actions RENAME TO corporate_actions_v5;

            CREATE TABLE corporate_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                action_type TEXT NOT NULL
                    CHECK (action_type IN ('dividend', 'split')),
                effective_at TEXT NOT NULL,
                cash_amount REAL,
                split_ratio REAL,
                currency TEXT,
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
                id,
                instrument_id,
                action_type,
                effective_at,
                cash_amount,
                split_ratio,
                currency,
                source_provider,
                source_timestamp,
                retrieved_at,
                created_at
            )
            SELECT
                id,
                instrument_id,
                action_type,
                effective_at,
                cash_amount,
                split_ratio,
                currency,
                source_provider,
                source_timestamp,
                retrieved_at,
                created_at
            FROM corporate_actions_v5;

            DROP TABLE corporate_actions_v5;

            CREATE INDEX idx_corporate_actions_instrument_effective
            ON corporate_actions (
                instrument_id,
                effective_at
            );

            CREATE INDEX idx_corporate_actions_pit
            ON corporate_actions (
                instrument_id,
                retrieved_at,
                effective_at
            );
            """
        )


__all__ = ["AthenaConnection", "AthenaDatabase"]

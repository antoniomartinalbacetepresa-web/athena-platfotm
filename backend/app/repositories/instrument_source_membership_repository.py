from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.database.athena_database import AthenaDatabase


class InstrumentSourceMembershipRepository:
    """Tracks which catalog sources currently back each instrument listing."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()

        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS instrument_source_memberships (
                    instrument_id INTEGER NOT NULL,
                    source_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (instrument_id, source_id),
                    FOREIGN KEY (instrument_id)
                        REFERENCES instruments(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_instrument_source_memberships_source_active
                ON instrument_source_memberships (
                    source_id,
                    is_active,
                    instrument_id
                );
                """
            )

    def mark_seen_many(
        self,
        *,
        source_id: str,
        instrument_ids: Iterable[int],
        seen_at: str | None = None,
    ) -> int:
        normalized_source = self._normalize_source_id(source_id)
        normalized_ids = tuple(dict.fromkeys(int(value) for value in instrument_ids))

        if not normalized_ids:
            return 0

        timestamp = seen_at or datetime.now(timezone.utc).isoformat()
        self.initialize()

        with self._database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO instrument_source_memberships (
                    instrument_id,
                    source_id,
                    first_seen_at,
                    last_seen_at,
                    is_active
                ) VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(instrument_id, source_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    is_active = 1
                """,
                [
                    (instrument_id, normalized_source, timestamp, timestamp)
                    for instrument_id in normalized_ids
                ],
            )

        return len(normalized_ids)

    def deactivate_missing_for_source(
        self,
        *,
        source_id: str,
        active_instrument_ids: Iterable[int],
    ) -> int:
        normalized_source = self._normalize_source_id(source_id)
        active_ids = {int(value) for value in active_instrument_ids}
        self.initialize()

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT instrument_id
                FROM instrument_source_memberships
                WHERE source_id = ?
                  AND is_active = 1
                """,
                (normalized_source,),
            ).fetchall()

            ids_to_deactivate = [
                int(row["instrument_id"])
                for row in rows
                if int(row["instrument_id"]) not in active_ids
            ]

            if not ids_to_deactivate:
                return 0

            connection.executemany(
                """
                UPDATE instrument_source_memberships
                SET is_active = 0
                WHERE source_id = ?
                  AND instrument_id = ?
                  AND is_active = 1
                """,
                [
                    (normalized_source, instrument_id)
                    for instrument_id in ids_to_deactivate
                ],
            )

        return len(ids_to_deactivate)

    def count_active_for_source(self, source_id: str) -> int:
        normalized_source = self._normalize_source_id(source_id)
        self.initialize()

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM instrument_source_memberships
                WHERE source_id = ?
                  AND is_active = 1
                """,
                (normalized_source,),
            ).fetchone()

        return 0 if row is None else int(row["total"])

    def list_active_sources_for_instrument(self, instrument_id: int) -> list[str]:
        self.initialize()

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_id
                FROM instrument_source_memberships
                WHERE instrument_id = ?
                  AND is_active = 1
                ORDER BY source_id ASC
                """,
                (int(instrument_id),),
            ).fetchall()

        return [str(row["source_id"]) for row in rows]

    def _normalize_source_id(self, source_id: str) -> str:
        normalized = str(source_id).strip()
        if not normalized:
            raise ValueError("source_id es obligatorio.")
        return normalized

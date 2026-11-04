from __future__ import annotations

import json
from typing import Iterable

from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import NormalizedDatum


class NormalizedDataRepository:
    """Persist point-in-time normalized observations with full provenance."""

    def __init__(self, database: AthenaDatabase) -> None:
        self._database = database

    def initialize(self) -> None:
        self._database.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS normalized_data_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric TEXT NOT NULL,
                    entity_id TEXT,
                    value_json TEXT NOT NULL,
                    data_kind TEXT NOT NULL,
                    unit TEXT,
                    currency TEXT,
                    quality_score REAL,
                    confidence_score REAL,
                    source_id TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    effective_at TEXT,
                    published_at TEXT,
                    source_timestamp TEXT,
                    available_at TEXT,
                    source_version TEXT,
                    raw_identifier TEXT,
                    normalized_identifier TEXT,
                    source_url TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (
                        metric,
                        entity_id,
                        source_id,
                        effective_at,
                        published_at,
                        source_version,
                        value_json
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_normalized_data_metric_entity_time
                ON normalized_data_observations (
                    metric,
                    entity_id,
                    effective_at,
                    published_at
                );

                CREATE INDEX IF NOT EXISTS idx_normalized_data_source_retrieved
                ON normalized_data_observations (
                    source_id,
                    retrieved_at
                );
                """
            )

            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(normalized_data_observations)"
                ).fetchall()
            }
            if "available_at" not in columns:
                connection.execute(
                    "ALTER TABLE normalized_data_observations ADD COLUMN available_at TEXT"
                )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_normalized_data_available_at
                ON normalized_data_observations (available_at)
                """
            )

            connection.execute(
                """
                DELETE FROM normalized_data_observations
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM normalized_data_observations
                    GROUP BY
                        metric,
                        COALESCE(entity_id, ''),
                        source_id,
                        COALESCE(effective_at, ''),
                        COALESCE(published_at, ''),
                        COALESCE(source_version, ''),
                        value_json
                )
                """
            )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_normalized_data_observation_identity
                ON normalized_data_observations (
                    metric,
                    COALESCE(entity_id, ''),
                    source_id,
                    COALESCE(effective_at, ''),
                    COALESCE(published_at, ''),
                    COALESCE(source_version, ''),
                    value_json
                )
                """
            )

    def save(self, datum: NormalizedDatum) -> int:
        self.initialize()
        provenance = datum.provenance
        value_json = json.dumps(datum.value, ensure_ascii=False, sort_keys=True)
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO normalized_data_observations (
                    metric, entity_id, value_json, data_kind, unit, currency,
                    quality_score, confidence_score, source_id, retrieved_at,
                    effective_at, published_at, source_timestamp, available_at,
                    source_version, raw_identifier, normalized_identifier, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datum.metric, datum.entity_id, value_json, datum.data_kind,
                    datum.unit, datum.currency, datum.quality_score,
                    datum.confidence_score, provenance.source_id,
                    provenance.retrieved_at, provenance.effective_at,
                    provenance.published_at, provenance.source_timestamp,
                    provenance.available_at, provenance.version,
                    provenance.raw_identifier, provenance.normalized_identifier,
                    provenance.source_url,
                ),
            )
            if cursor.rowcount == 1 and cursor.lastrowid is not None:
                return int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id FROM normalized_data_observations
                WHERE metric = ?
                  AND COALESCE(entity_id, '') = COALESCE(?, '')
                  AND source_id = ?
                  AND COALESCE(effective_at, '') = COALESCE(?, '')
                  AND COALESCE(published_at, '') = COALESCE(?, '')
                  AND COALESCE(source_version, '') = COALESCE(?, '')
                  AND value_json = ?
                ORDER BY id ASC LIMIT 1
                """,
                (
                    datum.metric, datum.entity_id, provenance.source_id,
                    provenance.effective_at, provenance.published_at,
                    provenance.version, value_json,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Normalized datum could not be persisted.")
            return int(row["id"])

    def save_many(self, data: Iterable[NormalizedDatum]) -> list[int]:
        return [self.save(datum) for datum in data]

    def get_latest(
        self,
        *,
        metric: str,
        entity_id: str | None = None,
        source_id: str | None = None,
        as_of: str | None = None,
    ) -> list[dict[str, object]]:
        self.initialize()
        clauses = ["metric = ?"]
        params: list[object] = [metric]
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if as_of is not None:
            clauses.append("available_at IS NOT NULL")
            clauses.append("available_at <= ?")
            params.append(as_of)
            clauses.append("retrieved_at <= ?")
            params.append(as_of)
        where_sql = " AND ".join(clauses)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM normalized_data_observations
                WHERE {where_sql}
                ORDER BY
                    COALESCE(effective_at, published_at, retrieved_at) DESC,
                    COALESCE(available_at, published_at, retrieved_at) DESC,
                    id DESC
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

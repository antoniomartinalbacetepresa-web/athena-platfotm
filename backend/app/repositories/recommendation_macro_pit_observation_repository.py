from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_macro_pit_observation_service import (
    RecommendationMacroPitObservationService,
)


class RecommendationMacroPitObservationRepository:
    """Append-only persistence for revision-aware macro observations."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationMacroPitObservationService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationMacroPitObservationService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_macro_pit_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_key TEXT NOT NULL UNIQUE,
                    series_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    source_provider TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(series_id, observed_at, available_at, source_provider, source_ref)
                );

                CREATE INDEX IF NOT EXISTS idx_macro_pit_series_available
                ON athena_macro_pit_observations(series_id, available_at, observed_at, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        key = str(validated["observationKey"])
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now(timezone.utc).isoformat()

        identity = (
            validated["seriesId"],
            validated["observedAt"],
            validated["availableAt"],
            validated["sourceProvider"],
            validated["sourceRef"],
        )
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_macro_pit_observations
                WHERE series_id = ? AND observed_at = ? AND available_at = ?
                  AND source_provider = ? AND source_ref = ?
                """,
                identity,
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["observation_key"] != key:
                    raise ValueError("La misma provenance macro produjo contenido distinto.")
                return self.validate_record(record)

            hash_row = connection.execute(
                "SELECT * FROM athena_macro_pit_observations WHERE observation_key = ?",
                (key,),
            ).fetchone()
            if hash_row is not None:
                return self.validate_record(self._row(hash_row))

            connection.execute(
                """
                INSERT INTO athena_macro_pit_observations (
                    observation_key, series_id, observed_at, available_at,
                    source_provider, source_ref, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (key, *identity, serialized, created_at),
            )
            row = connection.execute(
                "SELECT * FROM athena_macro_pit_observations WHERE observation_key = ?",
                (key,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_key(self, *, observation_key: str) -> dict[str, Any]:
        self.initialize()
        key = str(observation_key or "").strip().lower()
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_macro_pit_observations WHERE observation_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe Macro PIT observation con esa identidad.")
        return self.validate_record(self._row(row))

    def get_series_at_or_before(
        self,
        *,
        series_id: str,
        as_of: datetime,
        observed_start: datetime | None = None,
        observed_end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        normalized_series = str(series_id or "").strip().upper()
        if not normalized_series:
            raise ValueError("series_id es obligatorio.")
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        clauses = ["series_id = ?", "available_at <= ?"]
        params: list[object] = [normalized_series, cutoff]
        if observed_start is not None:
            if observed_start.tzinfo is None or observed_start.utcoffset() is None:
                raise ValueError("observed_start debe incluir zona horaria.")
            clauses.append("observed_at >= ?")
            params.append(observed_start.astimezone(timezone.utc).isoformat())
        if observed_end is not None:
            if observed_end.tzinfo is None or observed_end.utcoffset() is None:
                raise ValueError("observed_end debe incluir zona horaria.")
            clauses.append("observed_at <= ?")
            params.append(observed_end.astimezone(timezone.utc).isoformat())

        query = f"""
            SELECT * FROM athena_macro_pit_observations
            WHERE {' AND '.join(clauses)}
            ORDER BY observed_at ASC, available_at ASC, id ASC
        """
        with self._database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self.validate_record(self._row(row)) for row in rows]

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro Macro PIT carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        expected = {
            "observation_key": validated["observationKey"],
            "series_id": validated["seriesId"],
            "observed_at": validated["observedAt"],
            "available_at": validated["availableAt"],
            "source_provider": validated["sourceProvider"],
            "source_ref": validated["sourceRef"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con Macro PIT canónico.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar Macro PIT persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de Macro PIT no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "observation_key": str(row["observation_key"]),
            "series_id": str(row["series_id"]),
            "observed_at": str(row["observed_at"]),
            "available_at": str(row["available_at"]),
            "source_provider": str(row["source_provider"]),
            "source_ref": str(row["source_ref"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

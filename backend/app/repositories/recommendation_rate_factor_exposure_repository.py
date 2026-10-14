from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_rate_factor_exposure_service import (
    RecommendationRateFactorExposureService,
)


class RecommendationRateFactorExposureRepository:
    """Append-only tamper-evident storage for sealed PIT rates exposure."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationRateFactorExposureService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationRateFactorExposureService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_rate_factor_exposures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_exposure_key TEXT NOT NULL UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    rate_series_id TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(instrument_id, rate_series_id, as_of)
                );

                CREATE INDEX IF NOT EXISTS idx_rate_factor_instrument_asof
                ON athena_rate_factor_exposures(instrument_id, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        key = str(validated["factorExposureKey"])
        identity = (
            int(validated["instrumentId"]),
            str(validated["rateSeriesId"]),
            str(validated["asOf"]),
        )
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM athena_rate_factor_exposures
                WHERE instrument_id = ? AND rate_series_id = ? AND as_of = ?
                """,
                identity,
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["factor_exposure_key"] != key:
                    raise ValueError("La misma identidad de rates produjo un artefacto distinto.")
                return self.validate_record(record)

            connection.execute(
                """
                INSERT INTO athena_rate_factor_exposures (
                    factor_exposure_key, instrument_id, rate_series_id,
                    as_of, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, *identity, serialized, created_at),
            )
            row = connection.execute(
                "SELECT * FROM athena_rate_factor_exposures WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_key(self, *, factor_exposure_key: str) -> dict[str, Any]:
        self.initialize()
        key = str(factor_exposure_key or "").strip().lower()
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_rate_factor_exposures WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe rates factor exposure con esa identidad.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro rates carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        expected = {
            "factor_exposure_key": validated["factorExposureKey"],
            "instrument_id": validated["instrumentId"],
            "rate_series_id": validated["rateSeriesId"],
            "as_of": validated["asOf"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con rates canónico.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar rates exposure persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de rates no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "factor_exposure_key": str(row["factor_exposure_key"]),
            "instrument_id": int(row["instrument_id"]),
            "rate_series_id": str(row["rate_series_id"]),
            "as_of": str(row["as_of"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

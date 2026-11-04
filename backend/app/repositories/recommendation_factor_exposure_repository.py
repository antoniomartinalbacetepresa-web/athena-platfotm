from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_market_beta_exposure_service import RecommendationMarketBetaExposureService


class RecommendationFactorExposureRepository:
    """Append-only tamper-evident storage for validated factor exposure artifacts."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationMarketBetaExposureService | None = None,
    ) -> None:
        self._database = database or AthenaDatabase()
        self._service = service or RecommendationMarketBetaExposureService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_factor_exposure_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_exposure_key TEXT NOT NULL UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    benchmark_instrument_id INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_factor_exposure_instrument_asof
                ON athena_factor_exposure_artifacts(instrument_id, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(dict(artifact))
        key = str(validated["factorExposureKey"])
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now().astimezone().isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_factor_exposure_artifacts WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact"] != validated:
                    raise ValueError("factorExposureKey ya existe con contenido distinto.")
                return self.validate_record(record)
            connection.execute(
                """
                INSERT INTO athena_factor_exposure_artifacts (
                    factor_exposure_key, instrument_id, benchmark_instrument_id,
                    as_of, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    int(validated["instrumentId"]),
                    int(validated["benchmarkInstrumentId"]),
                    str(validated["asOf"]),
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_factor_exposure_artifacts WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get(self, *, factor_exposure_key: str) -> dict[str, Any] | None:
        self.initialize()
        key = str(factor_exposure_key or "").strip().lower()
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise ValueError("factor_exposure_key debe ser SHA-256 hexadecimal.")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_factor_exposure_artifacts WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
        return None if row is None else self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro factor exposure carece de artifact válido.")
        validated = self._service.validate_artifact(dict(artifact))
        expected = {
            "factor_exposure_key": validated["factorExposureKey"],
            "instrument_id": validated["instrumentId"],
            "benchmark_instrument_id": validated["benchmarkInstrumentId"],
            "as_of": validated["asOf"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact canónico.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar factor exposure persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de factor exposure no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "factor_exposure_key": str(row["factor_exposure_key"]),
            "instrument_id": int(row["instrument_id"]),
            "benchmark_instrument_id": int(row["benchmark_instrument_id"]),
            "as_of": str(row["as_of"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

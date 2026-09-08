from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_forecast_error_oos_summary_service import (
    RecommendationResearchForecastErrorOosSummaryService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchForecastErrorOosSummaryRepository:
    """Append-only, tamper-evident storage for structural OOS error summaries."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationResearchForecastErrorOosSummaryService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationResearchForecastErrorOosSummaryService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_forecast_error_oos_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_hash TEXT NOT NULL UNIQUE,
                    summary_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_oos_summary_method_horizon
                ON athena_research_forecast_error_oos_summaries(method, horizon_seconds, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        summary_hash = self._sha256(validated.get("summaryHash"), "summaryHash")
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
                "SELECT * FROM athena_research_forecast_error_oos_summaries WHERE summary_hash = ?",
                (summary_hash,),
            ).fetchone()
            if existing is not None:
                return self.validate_record(self._row(existing))
            connection.execute(
                """
                INSERT INTO athena_research_forecast_error_oos_summaries (
                    summary_hash, summary_id, method, horizon_seconds, as_of, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_hash,
                    str(validated["summaryId"]),
                    str(validated["method"]),
                    int(validated["horizonSeconds"]),
                    str(validated["asOf"]),
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_forecast_error_oos_summaries WHERE summary_hash = ?",
                (summary_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, summary_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(summary_hash, "summary_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_forecast_error_oos_summaries WHERE summary_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe un OOS forecast error summary con ese hash.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro OOS forecast summary carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        expected = {
            "summary_hash": validated["summaryHash"],
            "summary_id": validated["summaryId"],
            "method": validated["method"],
            "horizon_seconds": validated["horizonSeconds"],
            "as_of": validated["asOf"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact canónico.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar OOS forecast summary persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de OOS forecast summary no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "summary_hash": str(row["summary_hash"]),
            "summary_id": str(row["summary_id"]),
            "method": str(row["method"]),
            "horizon_seconds": int(row["horizon_seconds"]),
            "as_of": str(row["as_of"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_forecast_error_service import (
    RecommendationResearchForecastErrorService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchForecastErrorRepository:
    """Append-only, tamper-evident storage for deterministic forecast errors."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationResearchForecastErrorService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationResearchForecastErrorService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_forecast_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_hash TEXT NOT NULL UNIQUE,
                    specification_hash TEXT NOT NULL,
                    outcome_hash TEXT NOT NULL,
                    cycle_hash TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (specification_hash, outcome_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_research_forecast_error_cycle
                ON athena_research_forecast_errors(cycle_hash, horizon_seconds, id);

                CREATE INDEX IF NOT EXISTS idx_research_forecast_error_outcome_time
                ON athena_research_forecast_errors(outcome_hash, created_at, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        error_hash = self._sha256(validated["errorHash"], "errorHash")
        specification_hash = self._sha256(validated["specificationHash"], "specificationHash")
        outcome_hash = self._sha256(validated["outcomeHash"], "outcomeHash")
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing_pair = connection.execute(
                """
                SELECT * FROM athena_research_forecast_errors
                WHERE specification_hash = ? AND outcome_hash = ?
                """,
                (specification_hash, outcome_hash),
            ).fetchone()
            if existing_pair is not None:
                record = self._row(existing_pair)
                if record["error_hash"] != error_hash:
                    raise ValueError("El mismo specification/outcome produjo un forecast error distinto.")
                return self.validate_record(record)

            existing_hash = connection.execute(
                "SELECT * FROM athena_research_forecast_errors WHERE error_hash = ?",
                (error_hash,),
            ).fetchone()
            if existing_hash is not None:
                raise ValueError("errorHash ya está persistido con otra identidad.")

            connection.execute(
                """
                INSERT INTO athena_research_forecast_errors (
                    error_hash, specification_hash, outcome_hash, cycle_hash,
                    instrument_id, symbol, horizon_seconds, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    error_hash,
                    specification_hash,
                    outcome_hash,
                    validated["cycleHash"],
                    validated["instrumentId"],
                    validated["symbol"],
                    validated["horizonSeconds"],
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_forecast_errors WHERE error_hash = ?",
                (error_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, error_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(error_hash, "error_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_forecast_errors WHERE error_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe un research forecast error con ese hash.")
        return self.validate_record(self._row(row))

    def get_for_outcomes_at_or_before(
        self,
        *,
        outcome_hashes: list[str] | tuple[str, ...],
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        self.initialize()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        normalized_hashes = [self._sha256(value, "outcome_hash") for value in outcome_hashes]
        if not normalized_hashes:
            return []
        if len(normalized_hashes) > 5000:
            raise ValueError("outcome_hashes supera el límite de 5000.")
        if len(set(normalized_hashes)) != len(normalized_hashes):
            raise ValueError("outcome_hashes contiene duplicados.")
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in normalized_hashes)
        query = f"""
            SELECT *
            FROM athena_research_forecast_errors
            WHERE outcome_hash IN ({placeholders})
              AND created_at <= ?
            ORDER BY horizon_seconds ASC, outcome_hash ASC, id ASC
        """
        with self._database.connect() as connection:
            rows = connection.execute(query, (*normalized_hashes, cutoff)).fetchall()
        return [self.validate_record(self._row(row)) for row in rows]

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro forecast error carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        expected = {
            "error_hash": validated["errorHash"],
            "specification_hash": validated["specificationHash"],
            "outcome_hash": validated["outcomeHash"],
            "cycle_hash": validated["cycleHash"],
            "instrument_id": validated["instrumentId"],
            "symbol": validated["symbol"],
            "horizon_seconds": validated["horizonSeconds"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact canónico.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar forecast error persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de forecast error no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "error_hash": str(row["error_hash"]),
            "specification_hash": str(row["specification_hash"]),
            "outcome_hash": str(row["outcome_hash"]),
            "cycle_hash": str(row["cycle_hash"]),
            "instrument_id": str(row["instrument_id"]),
            "symbol": str(row["symbol"]),
            "horizon_seconds": int(row["horizon_seconds"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchEvaluationSpecificationRepository:
    """Append-only, tamper-evident storage for truly ex-ante evaluation specifications."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationResearchEvaluationSpecificationService | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationResearchEvaluationSpecificationService()
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_evaluation_specifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specification_id TEXT NOT NULL UNIQUE,
                    specification_hash TEXT NOT NULL UNIQUE,
                    cycle_hash TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    cycle_as_of TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (cycle_hash, horizon_seconds)
                );

                CREATE INDEX IF NOT EXISTS idx_research_evaluation_spec_cycle
                ON athena_research_evaluation_specifications(cycle_hash, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        specification_id = str(validated["specificationId"])
        specification_hash = self._sha256(validated["specificationHash"], "specificationHash")
        cycle_hash = self._sha256(validated["cycleHash"], "cycleHash")
        horizon_seconds = int(validated["horizonSeconds"])
        sealed_at = self._aware_utc(self._now_provider(), "now_provider")
        period_end = self._aware_iso(validated.get("periodEnd"), "periodEnd")
        if sealed_at >= period_end:
            raise ValueError(
                "El horizonte ya terminó: esta previsión no puede sellarse retrospectivamente como ex-ante."
            )
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = sealed_at.isoformat()

        with self._database.connect() as connection:
            existing_id = connection.execute(
                "SELECT * FROM athena_research_evaluation_specifications WHERE specification_id = ?",
                (specification_id,),
            ).fetchone()
            if existing_id is not None:
                record = self._row(existing_id)
                if record["specification_hash"] != specification_hash:
                    raise ValueError("specificationId ya existe con contenido distinto; no puede reescribirse.")
                return self.validate_record(record)

            existing_target = connection.execute(
                """
                SELECT * FROM athena_research_evaluation_specifications
                WHERE cycle_hash = ? AND horizon_seconds = ?
                """,
                (cycle_hash, horizon_seconds),
            ).fetchone()
            if existing_target is not None:
                record = self._row(existing_target)
                if record["specification_hash"] != specification_hash:
                    raise ValueError("El ciclo ya tiene una previsión distinta para ese horizonte; no se permite mover el objetivo.")
                return self.validate_record(record)

            existing_hash = connection.execute(
                "SELECT * FROM athena_research_evaluation_specifications WHERE specification_hash = ?",
                (specification_hash,),
            ).fetchone()
            if existing_hash is not None:
                raise ValueError("specificationHash ya existe con otra identidad.")

            connection.execute(
                """
                INSERT INTO athena_research_evaluation_specifications (
                    specification_id, specification_hash, cycle_hash, instrument_id,
                    symbol, cycle_as_of, horizon_seconds, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    specification_id,
                    specification_hash,
                    cycle_hash,
                    validated["instrumentId"],
                    validated["symbol"],
                    validated["cycleAsOf"],
                    horizon_seconds,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_evaluation_specifications WHERE specification_hash = ?",
                (specification_hash,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_hash(self, *, specification_hash: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(specification_hash, "specification_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_evaluation_specifications WHERE specification_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe una evaluation specification con ese hash.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro de evaluation specification carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        period_end = self._aware_iso(validated.get("periodEnd"), "periodEnd")
        if created_at >= period_end:
            raise ValueError("La specification persistida no fue sellada antes de terminar su horizonte.")
        expected = {
            "specification_id": validated["specificationId"],
            "specification_hash": validated["specificationHash"],
            "cycle_hash": validated["cycleHash"],
            "instrument_id": validated["instrumentId"],
            "symbol": validated["symbol"],
            "cycle_as_of": validated["cycleAsOf"],
            "horizon_seconds": validated["horizonSeconds"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact canónico.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar evaluation specification persistida.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de evaluation specification no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "specification_id": str(row["specification_id"]),
            "specification_hash": str(row["specification_hash"]),
            "cycle_hash": str(row["cycle_hash"]),
            "instrument_id": str(row["instrument_id"]),
            "symbol": str(row["symbol"]),
            "cycle_as_of": str(row["cycle_as_of"]),
            "horizon_seconds": int(row["horizon_seconds"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _aware_iso(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

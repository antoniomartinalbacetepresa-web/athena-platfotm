from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_research_model_execution_receipt_service import (
    RecommendationResearchModelExecutionReceiptService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationResearchModelExecutionReceiptRepository:
    """Append-only storage for model execution receipts bound to one v3 forecast."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationResearchModelExecutionReceiptService | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._service = service or RecommendationResearchModelExecutionReceiptService()
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_research_model_execution_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_hash TEXT NOT NULL UNIQUE,
                    execution_id TEXT NOT NULL UNIQUE,
                    specification_hash TEXT NOT NULL UNIQUE,
                    cycle_hash TEXT NOT NULL,
                    model_artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_research_model_execution_receipt_cycle
                ON athena_research_model_execution_receipts(cycle_hash, id);
                """
            )

    def append(
        self,
        *,
        artifact: dict[str, Any],
        specification_record: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_against_specification(
            artifact=artifact,
            specification_record=specification_record,
        )
        receipt_hash = self._sha256(validated["receiptHash"], "receiptHash")
        specification_hash = self._sha256(
            validated["specificationHash"], "specificationHash"
        )
        execution_id = str(validated["executionId"])
        serialized = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        created_at = self._aware_utc(self._now_provider(), "now_provider")
        executed_at = self._aware_iso(validated["executedAt"], "executedAt")
        specification = specification_record["artifact"]
        period_start = self._aware_iso(specification["periodStart"], "periodStart")
        if executed_at > created_at:
            raise ValueError("La ejecución declarada aún no había ocurrido al persistir el recibo.")
        if created_at > period_start:
            raise ValueError("El recibo de ejecución debe sellarse antes o al inicio del periodo OOS.")

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_research_model_execution_receipts WHERE specification_hash = ?",
                (specification_hash,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["receipt_hash"] != receipt_hash:
                    raise ValueError(
                        "La specification ya tiene un recibo de ejecución distinto; no puede reescribirse."
                    )
                return self.validate_record(record, specification_record=specification_record)
            if connection.execute(
                "SELECT 1 FROM athena_research_model_execution_receipts WHERE execution_id = ?",
                (execution_id,),
            ).fetchone() is not None:
                raise ValueError("executionId ya está ligado a otra specification.")
            if connection.execute(
                "SELECT 1 FROM athena_research_model_execution_receipts WHERE receipt_hash = ?",
                (receipt_hash,),
            ).fetchone() is not None:
                raise ValueError("receiptHash ya existe con otra identidad.")
            connection.execute(
                """
                INSERT INTO athena_research_model_execution_receipts (
                    receipt_hash, execution_id, specification_hash, cycle_hash,
                    model_artifact_hash, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_hash,
                    execution_id,
                    specification_hash,
                    validated["cycleHash"],
                    validated["model"]["artifactHash"],
                    serialized,
                    created_at.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_research_model_execution_receipts WHERE receipt_hash = ?",
                (receipt_hash,),
            ).fetchone()
        return self.validate_record(self._row(row), specification_record=specification_record)

    def get_by_hash(
        self,
        *,
        receipt_hash: str,
        specification_record: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(receipt_hash, "receipt_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_model_execution_receipts WHERE receipt_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe un model execution receipt con ese hash.")
        return self.validate_record(self._row(row), specification_record=specification_record)

    def get_by_specification_hash(
        self,
        *,
        specification_hash: str,
        specification_record: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(specification_hash, "specification_hash")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_research_model_execution_receipts WHERE specification_hash = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("La evaluation specification no tiene model execution receipt persistido.")
        return self.validate_record(self._row(row), specification_record=specification_record)

    def validate_record(
        self,
        record: dict[str, Any],
        *,
        specification_record: dict[str, Any],
    ) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro de model execution receipt carece de artifact válido.")
        validated = self._service.validate_against_specification(
            artifact=artifact,
            specification_record=specification_record,
        )
        expected = {
            "receipt_hash": validated["receiptHash"],
            "execution_id": validated["executionId"],
            "specification_hash": validated["specificationHash"],
            "cycle_hash": validated["cycleHash"],
            "model_artifact_hash": validated["model"]["artifactHash"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con el recibo canónico.")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        executed_at = self._aware_iso(validated["executedAt"], "executedAt")
        period_start = self._aware_iso(specification_record["artifact"]["periodStart"], "periodStart")
        if executed_at > created_at or created_at > period_start:
            raise ValueError("El registro persistido viola el orden temporal del recibo.")
        return record

    def _row(self, row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar model execution receipt persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json del model execution receipt no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "receipt_hash": str(row["receipt_hash"]),
            "execution_id": str(row["execution_id"]),
            "specification_hash": str(row["specification_hash"]),
            "cycle_hash": str(row["cycle_hash"]),
            "model_artifact_hash": str(row["model_artifact_hash"]),
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

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_operating_margin_evidence_service import (
    RecommendationOperatingMarginEvidenceService,
)


class RecommendationOperatingMarginEvidenceRepository:
    """Append-only tamper-evident storage for resolved PIT operating-margin evidence."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationOperatingMarginEvidenceService | None = None,
    ) -> None:
        self._database = database or AthenaDatabase()
        self._service = service or RecommendationOperatingMarginEvidenceService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_operating_margin_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_key TEXT NOT NULL UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    cik TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    accession_number TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operating_margin_instrument_asof
                ON athena_operating_margin_evidence(instrument_id, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(dict(artifact))
        key = str(validated["evidenceKey"])
        serialized = json.dumps(validated, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_operating_margin_evidence WHERE evidence_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["artifact"] != validated:
                    raise ValueError("evidenceKey de operating margin ya existe con contenido distinto.")
                return record
            connection.execute(
                """INSERT INTO athena_operating_margin_evidence
                   (evidence_key, instrument_id, cik, as_of, available_at, accession_number, artifact_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    int(validated["instrumentId"]),
                    str(validated["cik"]),
                    str(validated["asOf"]),
                    str(validated["availableAt"]),
                    str(validated["accessionNumber"]),
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_operating_margin_evidence WHERE evidence_key = ?", (key,)
            ).fetchone()
        return self.validate_record(self._row(row))

    def get(self, *, evidence_key: str) -> dict[str, Any] | None:
        self.initialize()
        key = self._key(evidence_key)
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_operating_margin_evidence WHERE evidence_key = ?", (key,)
            ).fetchone()
        return None if row is None else self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro operating margin carece de artifact válido.")
        validated = self._service.validate_artifact(dict(artifact))
        expected = {
            "evidence_key": validated["evidenceKey"],
            "instrument_id": validated["instrumentId"],
            "cik": validated["cik"],
            "as_of": validated["asOf"],
            "available_at": validated["availableAt"],
            "accession_number": validated["accessionNumber"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con operating margin canónico.")
        return record

    @staticmethod
    def _key(value: object) -> str:
        key = str(value or "").strip().lower()
        if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
            raise ValueError("evidence_key debe ser SHA-256 hexadecimal.")
        return key

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de operating margin no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "evidence_key": str(row["evidence_key"]),
            "instrument_id": int(row["instrument_id"]),
            "cik": str(row["cik"]),
            "as_of": str(row["as_of"]),
            "available_at": str(row["available_at"]),
            "accession_number": str(row["accession_number"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

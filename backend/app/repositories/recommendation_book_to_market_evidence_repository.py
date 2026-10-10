from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationBookToMarketEvidenceRepository:
    """Append-only, tamper-evident storage for resolved PIT book-to-market evidence."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationBookToMarketEvidenceService | None = None,
    ) -> None:
        self._database = database or AthenaDatabase()
        self._service = service or RecommendationBookToMarketEvidenceService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_book_to_market_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_key TEXT NOT NULL UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    identity_key TEXT NOT NULL,
                    fundamental_evidence_key TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_book_to_market_instrument_asof
                ON athena_book_to_market_evidence(instrument_id, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._service.validate_artifact(artifact)
        evidence_key = self._sha256(validated.get("evidenceKey"), "evidenceKey")
        identity = validated.get("identityEvidence")
        fundamental = validated.get("fundamentalEvidence")
        if not isinstance(identity, dict) or not isinstance(fundamental, dict):
            raise ValueError("Book-to-market carece de evidencias upstream.")
        identity_key = self._sha256(identity.get("identityKey"), "identityKey")
        fundamental_key = self._sha256(
            fundamental.get("evidenceKey"),
            "fundamentalEvidenceKey",
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
                "SELECT * FROM athena_book_to_market_evidence WHERE evidence_key = ?",
                (evidence_key,),
            ).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["artifact"] != validated:
                    raise ValueError("evidenceKey book-to-market ya existe con otro contenido.")
                return record
            connection.execute(
                """
                INSERT INTO athena_book_to_market_evidence
                (evidence_key, instrument_id, as_of, identity_key, fundamental_evidence_key, artifact_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_key,
                    validated["instrumentId"],
                    validated["asOf"],
                    identity_key,
                    fundamental_key,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_book_to_market_evidence WHERE evidence_key = ?",
                (evidence_key,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_key(self, *, evidence_key: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(evidence_key, "evidence_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_book_to_market_evidence WHERE evidence_key = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe evidencia book-to-market con esa clave.")
        return self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro book-to-market carece de artifact válido.")
        validated = self._service.validate_artifact(artifact)
        identity = validated.get("identityEvidence")
        fundamental = validated.get("fundamentalEvidence")
        if not isinstance(identity, dict) or not isinstance(fundamental, dict):
            raise ValueError("Registro book-to-market perdió evidencias upstream.")
        expected = {
            "evidence_key": validated["evidenceKey"],
            "instrument_id": validated["instrumentId"],
            "as_of": validated["asOf"],
            "identity_key": identity["identityKey"],
            "fundamental_evidence_key": fundamental["evidenceKey"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Registro book-to-market manipulado: {field} no coincide.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar book-to-market persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json book-to-market inválido.") from exc
        return {
            "id": int(row["id"]),
            "evidence_key": str(row["evidence_key"]),
            "instrument_id": int(row["instrument_id"]),
            "as_of": str(row["as_of"]),
            "identity_key": str(row["identity_key"]),
            "fundamental_evidence_key": str(row["fundamental_evidence_key"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _sha256(raw: object, field: str) -> str:
        value = str(raw or "").strip().lower()
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return value

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_value_factor_exposure_service import (
    RecommendationValueFactorExposureService,
)


class RecommendationValueFactorExposureRepository:
    """Append-only tamper-evident storage for PIT value factor artifacts."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        service: RecommendationValueFactorExposureService | None = None,
    ) -> None:
        self._database = database or AthenaDatabase()
        self._service = service or RecommendationValueFactorExposureService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_value_factor_exposure_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_exposure_key TEXT NOT NULL UNIQUE,
                    instrument_id INTEGER NOT NULL,
                    issuer_id INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    book_to_market_evidence_key TEXT NOT NULL,
                    universe_fingerprint TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_value_factor_exposure_instrument_asof
                ON athena_value_factor_exposure_artifacts(instrument_id, as_of, id);
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
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_value_factor_exposure_artifacts WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                record = self.validate_record(self._row(existing))
                if record["artifact"] != validated:
                    raise ValueError("factorExposureKey de value ya existe con contenido distinto.")
                return record
            connection.execute(
                """
                INSERT INTO athena_value_factor_exposure_artifacts
                (factor_exposure_key, instrument_id, issuer_id, as_of,
                 book_to_market_evidence_key, universe_fingerprint, artifact_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    int(validated["instrumentId"]),
                    int(validated["issuerId"]),
                    str(validated["asOf"]),
                    str(validated["bookToMarketEvidenceKey"]),
                    str(validated["universeFingerprint"]),
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_value_factor_exposure_artifacts WHERE factor_exposure_key = ?",
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
                "SELECT * FROM athena_value_factor_exposure_artifacts WHERE factor_exposure_key = ?",
                (key,),
            ).fetchone()
        return None if row is None else self.validate_record(self._row(row))

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro value factor exposure carece de artifact válido.")
        validated = self._service.validate_artifact(dict(artifact))
        expected = {
            "factor_exposure_key": validated["factorExposureKey"],
            "instrument_id": validated["instrumentId"],
            "issuer_id": validated["issuerId"],
            "as_of": validated["asOf"],
            "book_to_market_evidence_key": validated["bookToMarketEvidenceKey"],
            "universe_fingerprint": validated["universeFingerprint"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con value artifact canónico.")
        return record

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar value factor exposure persistido.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de value factor exposure no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "factor_exposure_key": str(row["factor_exposure_key"]),
            "instrument_id": int(row["instrument_id"]),
            "issuer_id": int(row["issuer_id"]),
            "as_of": str(row["as_of"]),
            "book_to_market_evidence_key": str(row["book_to_market_evidence_key"]),
            "universe_fingerprint": str(row["universe_fingerprint"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationReconciledPortfolioWeightRepository:
    """Append-only, tamper-evident storage for canonical reconciled weight evidence."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        validator: RecommendationReconciledPortfolioWeightService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._validator = validator or RecommendationReconciledPortfolioWeightService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_reconciled_portfolio_weight_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weight_evidence_key TEXT NOT NULL UNIQUE,
                    portfolio_id TEXT NOT NULL,
                    reporting_currency TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    reconciliation_key TEXT NOT NULL,
                    portfolio_state_key TEXT NOT NULL,
                    valuation_fingerprint TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reconciled_weight_portfolio_asof
                ON athena_reconciled_portfolio_weight_evidence(portfolio_id, as_of, id);

                CREATE INDEX IF NOT EXISTS idx_reconciled_weight_reconciliation
                ON athena_reconciled_portfolio_weight_evidence(reconciliation_key, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._validator.validate_artifact(artifact)
        key = self._sha256(validated.get("weightEvidenceKey"), "weightEvidenceKey")
        serialized = self._serialize(validated)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_reconciled_portfolio_weight_evidence WHERE weight_evidence_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact_hash"] != artifact_hash:
                    raise ValueError("weightEvidenceKey ya existe con contenido distinto.")
                return self.validate_record(record)

            connection.execute(
                """
                INSERT INTO athena_reconciled_portfolio_weight_evidence (
                    weight_evidence_key, portfolio_id, reporting_currency, as_of,
                    reconciliation_key, portfolio_state_key, valuation_fingerprint,
                    artifact_hash, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    str(validated["portfolioId"]),
                    str(validated["reportingCurrency"]),
                    str(validated["asOf"]),
                    str(validated["reconciliationKey"]),
                    str(validated["portfolioStateKey"]),
                    str(validated["portfolioValuationEvidenceFingerprint"]),
                    artifact_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_reconciled_portfolio_weight_evidence WHERE weight_evidence_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("No se pudo recuperar weight evidence persistida.")
        return self.validate_record(self._row(row))

    def get_by_key(self, *, weight_evidence_key: str) -> dict[str, Any]:
        self.initialize()
        key = self._sha256(weight_evidence_key, "weight_evidence_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_reconciled_portfolio_weight_evidence WHERE weight_evidence_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe weight evidence persistida con ese weightEvidenceKey.")
        return self.validate_record(self._row(row))

    def require_weight_evidence(
        self,
        *,
        weight_evidence_key: str,
        portfolio_id: str,
        reporting_currency: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        record = self.get_by_key(weight_evidence_key=weight_evidence_key)
        artifact = record["artifact"]
        if str(artifact["portfolioId"]) != str(portfolio_id).strip():
            raise ValueError("Weight evidence pertenece a otra cartera.")
        if str(artifact["reportingCurrency"]).upper() != str(reporting_currency).strip().upper():
            raise ValueError("Weight evidence usa otra moneda de reporting.")
        stored_as_of = datetime.fromisoformat(str(artifact["asOf"]).replace("Z", "+00:00"))
        if stored_as_of != as_of:
            raise ValueError("Weight evidence debe corresponder exactamente al as_of solicitado.")
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro de weight evidence carece de artifact válido.")
        validated = self._validator.validate_artifact(artifact)
        serialized = self._serialize(validated)
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if record.get("artifact_hash") != expected_hash:
            raise ValueError("Weight evidence fue modificada tras persistirse.")

        expected = {
            "weight_evidence_key": validated["weightEvidenceKey"],
            "portfolio_id": validated["portfolioId"],
            "reporting_currency": validated["reportingCurrency"],
            "as_of": validated["asOf"],
            "reconciliation_key": validated["reconciliationKey"],
            "portfolio_state_key": validated["portfolioStateKey"],
            "valuation_fingerprint": validated["portfolioValuationEvidenceFingerprint"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con weight evidence.")
        return record

    @staticmethod
    def _serialize(value: dict[str, Any]) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Weight evidence contiene datos no serializables/no finitos.") from exc

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("Fila de weight evidence ausente.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de weight evidence no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "weight_evidence_key": str(row["weight_evidence_key"]),
            "portfolio_id": str(row["portfolio_id"]),
            "reporting_currency": str(row["reporting_currency"]),
            "as_of": str(row["as_of"]),
            "reconciliation_key": str(row["reconciliation_key"]),
            "portfolio_state_key": str(row["portfolio_state_key"]),
            "valuation_fingerprint": str(row["valuation_fingerprint"]),
            "artifact_hash": str(row["artifact_hash"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

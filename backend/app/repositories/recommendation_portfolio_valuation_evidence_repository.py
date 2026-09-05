from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_portfolio_valuation_evidence_service import (
    RecommendationPortfolioValuationEvidenceService,
)


class _ValuationValidator(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationPortfolioValuationEvidenceRepository:
    """Append-only store for verified PIT portfolio valuation artifacts."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        *,
        validator: _ValuationValidator | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._validator = validator or RecommendationPortfolioValuationEvidenceService()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_portfolio_valuation_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    valuation_fingerprint TEXT NOT NULL UNIQUE,
                    as_of TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_valuation_evidence_as_of
                ON athena_recommendation_portfolio_valuation_evidence(as_of, base_currency);
                """
            )

    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._validated_artifact(artifact)
        valuation_fingerprint = self._sha256(
            validated.get("portfolioValuationEvidenceFingerprint"),
            "portfolioValuationEvidenceFingerprint",
        )
        serialized = self._serialize(validated)
        as_of = self._aware_iso(validated.get("asOf"), "asOf").isoformat()
        base_currency = self._currency(validated.get("baseCurrency"), "baseCurrency")

        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_valuation_evidence
                WHERE valuation_fingerprint = ?
                """,
                (valuation_fingerprint,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None:
                    raise RuntimeError("No se pudo recuperar la valoración existente.")
                if record["artifact"] != validated:
                    raise ValueError("La valoración sellada es inmutable.")
                return record

            persisted_at = datetime.now(timezone.utc).isoformat()
            record_core = {
                "valuationFingerprint": valuation_fingerprint,
                "asOf": as_of,
                "baseCurrency": base_currency,
                "artifact": validated,
                "persistedAt": persisted_at,
            }
            record_fingerprint = self._fingerprint(record_core)
            connection.execute(
                """
                INSERT INTO athena_recommendation_portfolio_valuation_evidence (
                    valuation_fingerprint,
                    as_of,
                    base_currency,
                    artifact_json,
                    persisted_at,
                    record_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    valuation_fingerprint,
                    as_of,
                    base_currency,
                    serialized,
                    persisted_at,
                    record_fingerprint,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_valuation_evidence
                WHERE valuation_fingerprint = ?
                """,
                (valuation_fingerprint,),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la valoración sellada.")
        return result

    def get(self, *, valuation_fingerprint: str) -> dict[str, Any] | None:
        self.initialize()
        fingerprint = self._sha256(valuation_fingerprint, "valuation_fingerprint")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_valuation_evidence
                WHERE valuation_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de valoración debe ser un objeto.")
        valuation_fingerprint = self._sha256(
            record.get("valuation_fingerprint"), "valuation_fingerprint"
        )
        as_of = self._aware_iso(record.get("as_of"), "as_of").isoformat()
        base_currency = self._currency(record.get("base_currency"), "base_currency")
        persisted_at = self._aware_iso(
            record.get("persisted_at"), "persisted_at"
        ).isoformat()
        artifact = self._validated_artifact(record.get("artifact"))
        if artifact.get("portfolioValuationEvidenceFingerprint") != valuation_fingerprint:
            raise ValueError("El registro cambió el fingerprint de valoración.")
        if self._aware_iso(artifact.get("asOf"), "artifact.asOf").isoformat() != as_of:
            raise ValueError("El registro cambió as_of.")
        if self._currency(artifact.get("baseCurrency"), "artifact.baseCurrency") != base_currency:
            raise ValueError("El registro cambió la moneda base.")
        supplied_record_fingerprint = self._sha256(
            record.get("record_fingerprint"), "record_fingerprint"
        )
        core = {
            "valuationFingerprint": valuation_fingerprint,
            "asOf": as_of,
            "baseCurrency": base_currency,
            "artifact": artifact,
            "persistedAt": persisted_at,
        }
        if self._fingerprint(core) != supplied_record_fingerprint:
            raise ValueError("El registro de valoración fue modificado.")
        return record

    def _validated_artifact(self, artifact: object) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("La evidencia de valoración debe ser un objeto.")
        if self._validator.validate_artifact(artifact) is not artifact:
            raise ValueError("El validador sustituyó la evidencia de valoración.")
        return artifact

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "valuation_fingerprint": str(row["valuation_fingerprint"]),
            "as_of": str(row["as_of"]),
            "base_currency": str(row["base_currency"]),
            "artifact": artifact,
            "persisted_at": str(row["persisted_at"]),
            "record_fingerprint": str(row["record_fingerprint"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("La valoración contiene datos no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _currency(self, value: object, field: str) -> str:
        result = str(value or "").strip().upper()
        if len(result) != 3 or not result.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _aware_iso(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser fecha ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha ISO válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

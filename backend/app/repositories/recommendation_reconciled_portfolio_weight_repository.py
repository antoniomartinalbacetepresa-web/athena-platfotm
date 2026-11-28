from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
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
        self._validate_economics(validated)
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
        self._validate_economics(validated)
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
    def _validate_economics(artifact: dict[str, Any]) -> None:
        def finite(value: object, field: str, *, positive: bool = False) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field} debe ser numérico finito.")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"{field} debe ser numérico finito.")
            if positive and numeric <= 0.0:
                raise ValueError(f"{field} debe ser positivo.")
            if not positive and numeric < 0.0:
                raise ValueError(f"{field} no puede ser negativo.")
            return numeric

        cash_balance = finite(artifact.get("cashBalance"), "cashBalance")
        cash_weight = finite(artifact.get("cashWeight"), "cashWeight")
        invested = finite(artifact.get("investedPositionsValue"), "investedPositionsValue")
        total = finite(artifact.get("totalPortfolioValue"), "totalPortfolioValue", positive=True)
        if not math.isclose(total, cash_balance + invested, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Weight evidence no reconcilia totalPortfolioValue = cash + investedPositionsValue.")
        expected_cash_weight = cash_balance / total
        if not math.isclose(cash_weight, expected_cash_weight, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("cashWeight no coincide con cashBalance / totalPortfolioValue.")

        positions = artifact.get("positions")
        if not isinstance(positions, list):
            raise ValueError("Weight evidence perdió positions.")
        position_total = 0.0
        seen: set[int] = set()
        for index, item in enumerate(positions):
            if not isinstance(item, dict):
                raise ValueError("Weight evidence contiene posición inválida.")
            instrument_id = item.get("instrumentId")
            if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
                raise ValueError("Weight evidence contiene instrumentId no canónico.")
            if instrument_id in seen:
                raise ValueError("Weight evidence contiene instrumentId duplicado.")
            seen.add(instrument_id)
            position_value = finite(
                item.get("positionValueInReportingCurrency"),
                f"positions[{index}].positionValueInReportingCurrency",
                positive=True,
            )
            weight = finite(item.get("weight"), f"positions[{index}].weight")
            expected_weight = position_value / total
            if not math.isclose(weight, expected_weight, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Position weight no coincide con positionValue / totalPortfolioValue.")
            position_total += position_value
            if not math.isfinite(position_total):
                raise ValueError("La suma de posiciones dejó de ser finita.")
        if not math.isclose(position_total, invested, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("investedPositionsValue no coincide con la suma de posiciones.")
        if not math.isclose(cash_weight + sum(float(item["weight"]) for item in positions), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("Cash y posiciones no reconcilian al 100%.")

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

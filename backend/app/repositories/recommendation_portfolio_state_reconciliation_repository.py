from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecommendationPortfolioStateReconciliationRepository:
    """Append-only, tamper-evident storage for portfolio state reconciliations."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_portfolio_state_reconciliations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reconciliation_key TEXT NOT NULL UNIQUE,
                    portfolio_state_key TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    reporting_currency TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    reconciled INTEGER NOT NULL CHECK (reconciled IN (0, 1)),
                    artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (portfolio_state_key, reconciliation_key)
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_reconciliation_state
                ON athena_portfolio_state_reconciliations(portfolio_state_key, as_of, id);

                CREATE INDEX IF NOT EXISTS idx_portfolio_reconciliation_portfolio
                ON athena_portfolio_state_reconciliations(portfolio_id, as_of, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._validate_artifact(artifact)
        reconciliation_key = self._sha256(validated["reconciliationKey"], "reconciliationKey")
        serialized = self._serialize(validated)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_portfolio_state_reconciliations WHERE reconciliation_key = ?",
                (reconciliation_key,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact_hash"] != artifact_hash:
                    raise ValueError("reconciliationKey ya existe con contenido distinto.")
                return self.validate_record(record)

            connection.execute(
                """
                INSERT INTO athena_portfolio_state_reconciliations (
                    reconciliation_key, portfolio_state_key, portfolio_id,
                    reporting_currency, as_of, reconciled, artifact_hash,
                    artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reconciliation_key,
                    validated["portfolioStateKey"],
                    validated["portfolioId"],
                    validated["reportingCurrency"],
                    validated["asOf"],
                    1 if validated["reconciled"] else 0,
                    artifact_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_portfolio_state_reconciliations WHERE reconciliation_key = ?",
                (reconciliation_key,),
            ).fetchone()
        return self.validate_record(self._row(row))

    def get_by_key(self, *, reconciliation_key: str) -> dict[str, Any]:
        self.initialize()
        normalized = self._sha256(reconciliation_key, "reconciliation_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_portfolio_state_reconciliations WHERE reconciliation_key = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise ValueError("No existe una reconciliación persistida con ese reconciliationKey.")
        return self.validate_record(self._row(row))

    def require_reconciled(
        self,
        *,
        reconciliation_key: str,
        portfolio_id: str,
        reporting_currency: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        record = self.get_by_key(reconciliation_key=reconciliation_key)
        artifact = record["artifact"]
        if artifact["reconciled"] is not True:
            raise ValueError("La reconciliación persistida no está reconciled=true; downstream bloqueado.")
        if str(artifact["portfolioId"]) != str(portfolio_id).strip():
            raise ValueError("La reconciliación pertenece a otra cartera.")
        if str(artifact["reportingCurrency"]).upper() != str(reporting_currency).strip().upper():
            raise ValueError("La reconciliación usa otra moneda de reporting.")
        if datetime.fromisoformat(str(artifact["asOf"]).replace("Z", "+00:00")) != as_of:
            raise ValueError("La reconciliación debe corresponder exactamente al as_of downstream.")
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("Registro de reconciliación carece de artifact válido.")
        validated = self._validate_artifact(artifact)
        serialized = self._serialize(validated)
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if record.get("artifact_hash") != expected_hash:
            raise ValueError("Artifact de reconciliación fue modificado tras persistirse.")
        expected = {
            "reconciliation_key": validated["reconciliationKey"],
            "portfolio_state_key": validated["portfolioStateKey"],
            "portfolio_id": validated["portfolioId"],
            "reporting_currency": validated["reportingCurrency"],
            "as_of": validated["asOf"],
            "reconciled": 1 if validated["reconciled"] else 0,
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"Campo persistido {field} no coincide con artifact de reconciliación.")
        return record

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("Reconciliación debe ser un objeto.")
        self._sha256(artifact.get("reconciliationKey"), "reconciliationKey")
        self._sha256(artifact.get("portfolioStateKey"), "portfolioStateKey")
        portfolio_id = str(artifact.get("portfolioId") or "").strip()
        if not portfolio_id:
            raise ValueError("portfolioId es obligatorio en reconciliación.")
        currency = str(artifact.get("reportingCurrency") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("reportingCurrency de reconciliación es inválida.")
        as_of = str(artifact.get("asOf") or "").strip()
        try:
            parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("asOf de reconciliación debe ser ISO válido.") from exc
        if parsed_as_of.tzinfo is None or parsed_as_of.utcoffset() is None:
            raise ValueError("asOf de reconciliación debe incluir zona horaria.")
        if not isinstance(artifact.get("reconciled"), bool):
            raise ValueError("reconciled debe ser booleano.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Reconciliación perdió no_advice.")
        if artifact.get("productionEligible") is not False:
            raise ValueError("Reconciliación intentó habilitar producción.")
        if artifact.get("isWeightingReady") is not False:
            raise ValueError("Reconciliación intentó habilitar weighting.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Reconciliación perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("Reconciliación intentó habilitar trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Reconciliación intentó promoción automática.")
        if policy.get("stateMismatchAction") != "fail_closed":
            raise ValueError("Reconciliación perdió fail-closed ante mismatch.")
        if policy.get("cashInference") != "forbidden" or policy.get("fxInference") != "forbidden":
            raise ValueError("Reconciliación intentó inferir cash o FX.")
        return artifact

    @staticmethod
    def _serialize(artifact: dict[str, Any]) -> str:
        return json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        if row is None:
            raise RuntimeError("No se pudo recuperar reconciliación persistida.")
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("artifact_json de reconciliación no es JSON válido.") from exc
        return {
            "id": int(row["id"]),
            "reconciliation_key": str(row["reconciliation_key"]),
            "portfolio_state_key": str(row["portfolio_state_key"]),
            "portfolio_id": str(row["portfolio_id"]),
            "reporting_currency": str(row["reporting_currency"]),
            "as_of": str(row["as_of"]),
            "reconciled": int(row["reconciled"]),
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

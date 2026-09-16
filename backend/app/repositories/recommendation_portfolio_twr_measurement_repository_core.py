from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOTAL_VALUE_SCOPE = "total_net_liquidation_value_in_reporting_currency"
_FINAL_SCHEMA = "athena_portfolio_twr_final_measurement_v1"


class RecommendationPortfolioTwrMeasurementRepository:
    """Append-only, tamper-evident storage for final server-side TWR artifacts."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_portfolio_twr_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measurement_key TEXT NOT NULL UNIQUE,
                    ledger_measurement_key TEXT NOT NULL,
                    core_measurement_key TEXT NOT NULL,
                    reconciliation_key TEXT NOT NULL,
                    portfolio_state_key TEXT NOT NULL,
                    ledger_head_hash TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    reporting_currency TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    time_weighted_return REAL NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_twr_measurement_portfolio
                ON athena_portfolio_twr_measurements(portfolio_id, period_end, as_of, id);

                CREATE INDEX IF NOT EXISTS idx_portfolio_twr_measurement_reconciliation
                ON athena_portfolio_twr_measurements(reconciliation_key, id);
                """
            )

    def append(self, *, artifact: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        validated = self._validate_artifact(artifact)
        serialized = self._serialize(validated)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created_at = datetime.now().astimezone().isoformat()

        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_portfolio_twr_measurements WHERE measurement_key = ?",
                (validated["measurementKey"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record["artifact_hash"] != artifact_hash:
                    raise ValueError("measurementKey already exists with different TWR content")
                return self.validate_record(record)

            connection.execute(
                """
                INSERT INTO athena_portfolio_twr_measurements (
                    measurement_key, ledger_measurement_key, core_measurement_key,
                    reconciliation_key, portfolio_state_key, ledger_head_hash,
                    portfolio_id, reporting_currency, period_start, period_end, as_of,
                    time_weighted_return, artifact_hash, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validated["measurementKey"],
                    validated["ledgerMeasurementKey"],
                    validated["coreMeasurementKey"],
                    validated["stateIntegrity"]["reconciliationKey"],
                    validated["stateIntegrity"]["portfolioStateKey"],
                    validated["serverSideLedger"]["ledgerHeadHash"],
                    validated["portfolioId"],
                    validated["reportingCurrency"],
                    validated["periodStart"],
                    validated["periodEnd"],
                    validated["asOf"],
                    validated["timeWeightedReturn"],
                    artifact_hash,
                    serialized,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_portfolio_twr_measurements WHERE measurement_key = ?",
                (validated["measurementKey"],),
            ).fetchone()
        if row is None:
            raise RuntimeError("persisted TWR measurement could not be reloaded")
        return self.validate_record(self._row(row))

    def get_by_key(self, *, measurement_key: str) -> dict[str, Any]:
        self.initialize()
        key = self._sha256(measurement_key, "measurement_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_portfolio_twr_measurements WHERE measurement_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No persisted portfolio TWR measurement exists for that measurementKey")
        return self.validate_record(self._row(row))

    def require_measurement(
        self,
        *,
        measurement_key: str,
        portfolio_id: str,
        reporting_currency: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        for value, field in ((period_start, "period_start"), (period_end, "period_end"), (as_of, "as_of")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field} must include timezone")
        record = self.get_by_key(measurement_key=measurement_key)
        artifact = record["artifact"]
        if artifact["portfolioId"] != str(portfolio_id).strip():
            raise ValueError("TWR measurement belongs to another portfolio")
        if artifact["reportingCurrency"] != str(reporting_currency).strip().upper():
            raise ValueError("TWR measurement uses another reporting currency")
        comparisons = (
            (artifact["periodStart"], period_start, "period_start"),
            (artifact["periodEnd"], period_end, "period_end"),
            (artifact["asOf"], as_of, "as_of"),
        )
        for stored, requested, field in comparisons:
            if datetime.fromisoformat(str(stored).replace("Z", "+00:00")) != requested:
                raise ValueError(f"TWR measurement {field} does not match downstream request")
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("persisted TWR record has no valid artifact")
        validated = self._validate_artifact(artifact)
        serialized = self._serialize(validated)
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if record.get("artifact_hash") != expected_hash:
            raise ValueError("persisted TWR artifact was modified")
        expected = {
            "measurement_key": validated["measurementKey"],
            "ledger_measurement_key": validated["ledgerMeasurementKey"],
            "core_measurement_key": validated["coreMeasurementKey"],
            "reconciliation_key": validated["stateIntegrity"]["reconciliationKey"],
            "portfolio_state_key": validated["stateIntegrity"]["portfolioStateKey"],
            "ledger_head_hash": validated["serverSideLedger"]["ledgerHeadHash"],
            "portfolio_id": validated["portfolioId"],
            "reporting_currency": validated["reportingCurrency"],
            "period_start": validated["periodStart"],
            "period_end": validated["periodEnd"],
            "as_of": validated["asOf"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"persisted TWR field {field} does not match artifact")
        persisted_return = self._finite(record.get("time_weighted_return"), "persisted time_weighted_return")
        if not math.isclose(
            persisted_return,
            float(validated["timeWeightedReturn"]),
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise ValueError("persisted TWR return does not match artifact")
        return record

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("TWR artifact must be an object")
        if artifact.get("module") != "portfolio_twr_measurement":
            raise ValueError("TWR artifact module is invalid")
        if artifact.get("status") != "measured_from_canonical_server_side_portfolio_ledger":
            raise ValueError("TWR artifact is not bound to canonical server-side ledger")
        final_key = self._sha256(artifact.get("measurementKey"), "measurementKey")
        self._sha256(artifact.get("ledgerMeasurementKey"), "ledgerMeasurementKey")
        self._sha256(artifact.get("coreMeasurementKey"), "coreMeasurementKey")
        if final_key != self._expected_final_key(artifact):
            raise ValueError("TWR measurementKey is not bound to the complete final artifact")
        portfolio_id = str(artifact.get("portfolioId") or "").strip()
        if not portfolio_id:
            raise ValueError("TWR artifact portfolioId is required")
        currency = str(artifact.get("reportingCurrency") or "").strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("TWR artifact reportingCurrency is invalid")
        for field in ("periodStart", "periodEnd", "asOf"):
            self._aware_iso(artifact.get(field), field)
        start = self._aware_iso(artifact["periodStart"], "periodStart")
        end = self._aware_iso(artifact["periodEnd"], "periodEnd")
        cutoff = self._aware_iso(artifact["asOf"], "asOf")
        if not start < end <= cutoff:
            raise ValueError("TWR artifact violates periodStart < periodEnd <= asOf")
        self._finite(artifact.get("timeWeightedReturn"), "timeWeightedReturn")
        self._finite(artifact.get("externalFlowTotal"), "externalFlowTotal")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("TWR artifact lost no_advice")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("TWR artifact attempted production/weighting enablement")

        state = artifact.get("stateIntegrity")
        if not isinstance(state, dict):
            raise ValueError("TWR artifact lost stateIntegrity")
        self._sha256(state.get("reconciliationKey"), "reconciliationKey")
        self._sha256(state.get("portfolioStateKey"), "portfolioStateKey")
        if state.get("reconciled") is not True or state.get("tamperVerified") is not True:
            raise ValueError("TWR artifact is not bound to reconciled/tamper-verified state")
        if state.get("gate") != "required_before_measurement":
            raise ValueError("TWR artifact lost state-integrity gate")

        ledger = artifact.get("serverSideLedger")
        if not isinstance(ledger, dict):
            raise ValueError("TWR artifact lost serverSideLedger")
        self._sha256(ledger.get("ledgerHeadHash"), "ledgerHeadHash")
        if ledger.get("serverSide") is not True or ledger.get("appendOnly") is not True:
            raise ValueError("TWR artifact lost server-side append-only ledger contract")
        if ledger.get("tamperEvidentHashChain") is not True:
            raise ValueError("TWR artifact lost ledger tamper-evidence")
        if ledger.get("callerSuppliedEventsAccepted") is not False:
            raise ValueError("TWR artifact accepted caller-supplied events")

        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("TWR artifact lost policy")
        if policy.get("valuationScope") != _TOTAL_VALUE_SCOPE:
            raise ValueError("TWR artifact does not use total NLV scope")
        if policy.get("callerSuppliedExternalCashFlowLedger") is not False:
            raise ValueError("TWR artifact accepted caller external-flow ledger")
        if policy.get("callerSuppliedInternalCashEvents") is not False:
            raise ValueError("TWR artifact accepted caller internal cash events")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("TWR artifact enabled automation")

        boundaries = artifact.get("boundaries")
        if not isinstance(boundaries, list) or len(boundaries) < 2:
            raise ValueError("TWR artifact lost valuation boundaries")
        external_events = artifact.get("externalFlowEvents")
        internal_events = artifact.get("internalCashEvents")
        if not isinstance(external_events, list) or not isinstance(internal_events, list):
            raise ValueError("TWR artifact lost ledger event evidence")
        for collection, name in ((external_events, "externalFlowEvents"), (internal_events, "internalCashEvents")):
            for index, event in enumerate(collection):
                if not isinstance(event, dict):
                    raise ValueError(f"{name}[{index}] must be an object")
                self._sha256(event.get("eventKey"), f"{name}[{index}].eventKey")
                if not str(event.get("source") or "").strip() or not str(event.get("sourceRef") or "").strip():
                    raise ValueError(f"{name}[{index}] lost provenance")
        return artifact

    @classmethod
    def _expected_final_key(cls, artifact: dict[str, Any]) -> str:
        identity = dict(artifact)
        identity.pop("measurementKey", None)
        identity["finalMeasurementSchema"] = _FINAL_SCHEMA
        return hashlib.sha256(cls._serialize(identity).encode("utf-8")).hexdigest()

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        try:
            artifact = json.loads(str(row["artifact_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("persisted TWR artifact_json is invalid") from exc
        return {
            "id": int(row["id"]),
            "measurement_key": str(row["measurement_key"]),
            "ledger_measurement_key": str(row["ledger_measurement_key"]),
            "core_measurement_key": str(row["core_measurement_key"]),
            "reconciliation_key": str(row["reconciliation_key"]),
            "portfolio_state_key": str(row["portfolio_state_key"]),
            "ledger_head_hash": str(row["ledger_head_hash"]),
            "portfolio_id": str(row["portfolio_id"]),
            "reporting_currency": str(row["reporting_currency"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "as_of": str(row["as_of"]),
            "time_weighted_return": float(row["time_weighted_return"]),
            "artifact_hash": str(row["artifact_hash"]),
            "artifact": artifact,
            "created_at": str(row["created_at"]),
        }

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
            raise ValueError("TWR artifact contains non-serializable/non-finite data") from exc

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} must be a SHA-256 hexadecimal fingerprint")
        return text

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be finite")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be finite") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    @staticmethod
    def _aware_iso(value: object, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} must be ISO datetime with timezone")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be valid ISO datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return parsed

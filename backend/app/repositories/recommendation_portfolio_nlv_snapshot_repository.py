from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

from app.database.athena_database import AthenaDatabase


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE = "total_net_liquidation_value_in_reporting_currency"
_PHASES = frozenset({"regular", "pre_external_flow", "post_external_flow"})


class RecommendationPortfolioNlvSnapshotRepository:
    """Append-only PIT store for independently observed total portfolio NLV snapshots."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_portfolio_nlv_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_key TEXT NOT NULL UNIQUE,
                    portfolio_id TEXT NOT NULL,
                    reporting_currency TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    value REAL NOT NULL,
                    source TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (portfolio_id, source, source_ref),
                    UNIQUE (portfolio_id, reporting_currency, observed_at, phase, source, source_ref)
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_nlv_pit
                ON athena_portfolio_nlv_snapshots(portfolio_id, reporting_currency, observed_at, available_at, id);
                """
            )

    def append(
        self,
        *,
        portfolio_id: str,
        reporting_currency: str,
        value: float,
        observed_at: datetime,
        available_at: datetime,
        phase: str,
        source: str,
        source_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        self.initialize()
        artifact = self._artifact(
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            value=value,
            observed_at=observed_at,
            available_at=available_at,
            phase=phase,
            source=source,
            source_ref=source_ref,
            as_of=as_of,
        )
        serialized = self._serialize(artifact)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM athena_portfolio_nlv_snapshots
                WHERE portfolio_id = ? AND source = ? AND source_ref = ?
                """,
                (artifact["portfolioId"], artifact["source"], artifact["sourceRef"]),
            ).fetchall()
            for row in rows:
                record = self.validate_record(self._row(row))
                if record["snapshot_key"] == artifact["snapshotKey"]:
                    if record["artifact_hash"] != artifact_hash:
                        raise ValueError("snapshotKey already exists with different NLV content")
                    return record
                raise ValueError("NLV provenance already identifies a different persisted snapshot")
            connection.execute(
                """
                INSERT INTO athena_portfolio_nlv_snapshots (
                    snapshot_key, portfolio_id, reporting_currency, observed_at,
                    available_at, phase, value, source, source_ref, artifact_hash,
                    artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact["snapshotKey"], artifact["portfolioId"], artifact["reportingCurrency"],
                    artifact["observedAt"], artifact["availableAt"], artifact["phase"], artifact["value"],
                    artifact["source"], artifact["sourceRef"], artifact_hash, serialized, created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM athena_portfolio_nlv_snapshots WHERE snapshot_key = ?",
                (artifact["snapshotKey"],),
            ).fetchone()
        if row is None:
            raise RuntimeError("persisted NLV snapshot could not be reloaded")
        return self.validate_record(self._row(row))

    def get_by_key(self, *, snapshot_key: str) -> dict[str, Any]:
        self.initialize()
        key = self._sha256(snapshot_key, "snapshot_key")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_portfolio_nlv_snapshots WHERE snapshot_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("No persisted portfolio NLV snapshot exists for that snapshotKey")
        return self.validate_record(self._row(row))

    def require_snapshot(
        self,
        *,
        snapshot_key: str,
        portfolio_id: str,
        reporting_currency: str,
        observed_at: datetime,
        phase: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        observed = self._aware(observed_at, "observed_at")
        record = self.get_by_key(snapshot_key=snapshot_key)
        artifact = record["artifact"]
        if artifact["portfolioId"] != self._text(portfolio_id, "portfolio_id"):
            raise ValueError("NLV snapshot belongs to another portfolio")
        if artifact["reportingCurrency"] != self._currency(reporting_currency):
            raise ValueError("NLV snapshot uses another reporting currency")
        if self._aware_iso(artifact["observedAt"], "observedAt") != observed:
            raise ValueError("NLV snapshot observed_at does not match requested boundary")
        expected_phase = self._phase(phase)
        if artifact["phase"] != expected_phase:
            raise ValueError("NLV snapshot phase does not match requested boundary")
        if self._aware_iso(artifact["availableAt"], "availableAt") > cutoff:
            raise ValueError("NLV snapshot was not available at requested as_of")
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("persisted NLV record has no valid artifact")
        validated = self._validate_artifact(artifact)
        serialized = self._serialize(validated)
        artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if record.get("artifact_hash") != artifact_hash:
            raise ValueError("persisted NLV artifact was modified")
        expected = {
            "snapshot_key": validated["snapshotKey"],
            "portfolio_id": validated["portfolioId"],
            "reporting_currency": validated["reportingCurrency"],
            "observed_at": validated["observedAt"],
            "available_at": validated["availableAt"],
            "phase": validated["phase"],
            "source": validated["source"],
            "source_ref": validated["sourceRef"],
        }
        for field, value in expected.items():
            if str(record.get(field)) != str(value):
                raise ValueError(f"persisted NLV field {field} does not match artifact")
        if not math.isclose(float(record.get("value")), float(validated["value"]), rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("persisted NLV value does not match artifact")
        return record

    def _artifact(self, **kwargs: Any) -> dict[str, Any]:
        cutoff = self._aware(kwargs["as_of"], "as_of")
        observed = self._aware(kwargs["observed_at"], "observed_at")
        available = self._aware(kwargs["available_at"], "available_at")
        if observed > available or available > cutoff:
            raise ValueError("NLV snapshot violates observed_at <= available_at <= as_of")
        value = self._finite(kwargs["value"], "value")
        if value < 0.0:
            raise ValueError("NLV snapshot value cannot be negative")
        body = {
            "schema": "athena_portfolio_nlv_snapshot_v1",
            "portfolioId": self._text(kwargs["portfolio_id"], "portfolio_id"),
            "reportingCurrency": self._currency(kwargs["reporting_currency"]),
            "value": value,
            "observedAt": observed.isoformat(),
            "availableAt": available.isoformat(),
            "phase": self._phase(kwargs["phase"]),
            "valuationScope": _SCOPE,
            "source": self._text(kwargs["source"], "source"),
            "sourceRef": self._text(kwargs["source_ref"], "source_ref"),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "cashInference": "forbidden",
                "liabilityInference": "forbidden",
                "unsettledInference": "forbidden",
                "fxInference": "forbidden",
                "valuationScope": _SCOPE,
            },
        }
        key_body = dict(body)
        key_body.pop("advisoryStatus")
        key_body.pop("productionEligible")
        key_body.pop("isWeightingReady")
        key_body.pop("policy")
        body["snapshotKey"] = hashlib.sha256(self._serialize(key_body).encode("utf-8")).hexdigest()
        return body

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("schema") != "athena_portfolio_nlv_snapshot_v1":
            raise ValueError("NLV artifact schema is invalid")
        expected_key = artifact.get("snapshotKey")
        self._sha256(expected_key, "snapshotKey")
        key_body = {k: v for k, v in artifact.items() if k not in {"snapshotKey", "advisoryStatus", "productionEligible", "isWeightingReady", "policy"}}
        if hashlib.sha256(self._serialize(key_body).encode("utf-8")).hexdigest() != expected_key:
            raise ValueError("NLV snapshotKey does not match artifact identity")
        self._text(artifact.get("portfolioId"), "portfolioId")
        self._currency(artifact.get("reportingCurrency"))
        observed = self._aware_iso(artifact.get("observedAt"), "observedAt")
        available = self._aware_iso(artifact.get("availableAt"), "availableAt")
        if observed > available:
            raise ValueError("NLV artifact violates observedAt <= availableAt")
        if self._finite(artifact.get("value"), "value") < 0.0:
            raise ValueError("NLV artifact value cannot be negative")
        self._phase(artifact.get("phase"))
        if artifact.get("valuationScope") != _SCOPE:
            raise ValueError("NLV artifact scope is not total NLV")
        self._text(artifact.get("source"), "source")
        self._text(artifact.get("sourceRef"), "sourceRef")
        if artifact.get("advisoryStatus") != "no_advice" or artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("NLV artifact violates research-only contract")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("NLV artifact lost policy")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("NLV artifact enabled automation")
        for field in ("cashInference", "liabilityInference", "unsettledInference", "fxInference"):
            if policy.get(field) != "forbidden":
                raise ValueError(f"NLV artifact allowed {field}")
        return artifact

    @staticmethod
    def _serialize(value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("NLV artifact contains non-serializable/non-finite data") from exc

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text

    @classmethod
    def _currency(cls, value: object) -> str:
        text = cls._text(value, "currency").upper()
        if len(text) != 3 or not text.isascii() or not text.isalpha():
            raise ValueError("currency must be a three-letter code")
        return text

    @classmethod
    def _phase(cls, value: object) -> str:
        text = cls._text(value, "phase").lower()
        if text not in _PHASES:
            raise ValueError("NLV phase must be regular, pre_external_flow or post_external_flow")
        return text

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be finite")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be finite") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field} must be finite")
        return number

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)

    @classmethod
    def _aware_iso(cls, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be valid ISO datetime") from exc
        return cls._aware(parsed, field)

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} must be SHA-256 hexadecimal")
        return text

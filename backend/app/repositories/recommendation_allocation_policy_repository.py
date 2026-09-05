from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationAllocationPolicyRepository:
    """Append-only portfolio sizing policy with no code-selected risk limits.

    The action model's exposure fraction is intentionally scoped to a single
    instrument sleeve. This registry defines the sleeve's maximum share of the
    user's reference capital and portfolio-level diversification constraints.
    All numerical limits are caller supplied and persisted before use; code has
    no default allocation weights, correlation cutoffs or staleness windows.
    """

    PROTOCOL_VERSION = "athena-allocation-policy-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database or AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_allocation_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_id TEXT NOT NULL UNIQUE,
                    registered_at TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    policy_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                """
            )

    def register(self, *, policy_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validate_draft(policy_draft)
        registered_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "registeredAt": registered_at}
        fingerprint = self._fingerprint(unsigned)
        policy = {**unsigned, "policyFingerprint": fingerprint}
        serialized = self._serialize(policy)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM athena_recommendation_allocation_policies WHERE policy_id = ?",
                (core["policyId"],),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if record is None or record["policy"] != policy:
                    raise ValueError("policyId ya existe; la política de asignación es inmutable.")
                return record
            connection.execute(
                """
                INSERT INTO athena_recommendation_allocation_policies (
                    policy_id, registered_at, policy_json, policy_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (core["policyId"], registered_at, serialized, fingerprint, created_at),
            )
            row = connection.execute(
                "SELECT * FROM athena_recommendation_allocation_policies WHERE policy_id = ?",
                (core["policyId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la política de asignación.")
        return result

    def get(self, *, policy_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._text(policy_id, "policy_id")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM athena_recommendation_allocation_policies WHERE policy_id = ?",
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de asignación debe ser un objeto.")
        policy = record.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El registro carece de policy.")
        if policy.get("policyId") != self._text(record.get("policy_id"), "policy_id"):
            raise ValueError("policyId fue modificado.")
        registered_at = self._aware(record.get("registered_at"), "registered_at")
        if self._aware(policy.get("registeredAt"), "registeredAt") != registered_at:
            raise ValueError("registeredAt fue modificado.")
        supplied = self._sha256(record.get("policy_fingerprint"), "policy_fingerprint")
        if policy.get("policyFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide.")
        unsigned = dict(policy)
        unsigned.pop("policyFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("La política fue modificada después de persistirse.")
        self._validate_persisted(policy)
        return record

    def _validate_draft(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("policy_draft debe ser un objeto.")
        if {"registeredAt", "policyFingerprint"}.intersection(value):
            raise ValueError("registeredAt/policyFingerprint los genera el registro.")
        if value.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión de política de asignación no compatible.")
        policy_id = self._text(value.get("policyId"), "policyId")
        base_currency = self._currency(value.get("baseCurrency"), "baseCurrency")
        sleeve = self._open_unit(value.get("maximumInstrumentSleeveWeight"), "maximumInstrumentSleeveWeight")
        reserve = self._unit(value.get("minimumCashReserveWeight"), "minimumCashReserveWeight")
        max_corr = self._unit(value.get("maximumAbsolutePairCorrelation"), "maximumAbsolutePairCorrelation")
        min_samples = self._positive_int(value.get("minimumCorrelationSampleCount"), "minimumCorrelationSampleCount")
        max_age = self._positive_int(value.get("maximumCorrelationAgeSeconds"), "maximumCorrelationAgeSeconds")
        if sleeve > 1.0 - reserve:
            raise ValueError("El sleeve máximo no puede consumir la reserva mínima de efectivo.")
        return {
            "artifactVersion": self.PROTOCOL_VERSION,
            "policyId": policy_id,
            "baseCurrency": base_currency,
            "maximumInstrumentSleeveWeight": sleeve,
            "minimumCashReserveWeight": reserve,
            "maximumAbsolutePairCorrelation": max_corr,
            "minimumCorrelationSampleCount": min_samples,
            "maximumCorrelationAgeSeconds": max_age,
            "semantics": {
                "referenceCapitalIsUserOwnedAllocationBase": True,
                "singleAssetExposureIsNotPortfolioWeight": True,
                "fullLongMeansFillInstrumentSleeveNotWholePortfolio": True,
                "reducedLongScalesInstrumentSleeveByFrozenEconomicContract": True,
                "sellTargetsZeroInstrumentWeight": True,
                "holdPreservesCurrentVerifiedWeight": True,
            },
            "policy": {
                "codeDefaultTargetWeight": False,
                "codeDefaultCorrelationThreshold": False,
                "codeDefaultStalenessThreshold": False,
                "automaticTrading": False,
            },
        }

    def _validate_persisted(self, value: dict[str, Any]) -> None:
        if value.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión persistida no compatible.")
        self._text(value.get("policyId"), "policyId")
        self._currency(value.get("baseCurrency"), "baseCurrency")
        sleeve = self._open_unit(value.get("maximumInstrumentSleeveWeight"), "maximumInstrumentSleeveWeight")
        reserve = self._unit(value.get("minimumCashReserveWeight"), "minimumCashReserveWeight")
        self._unit(value.get("maximumAbsolutePairCorrelation"), "maximumAbsolutePairCorrelation")
        self._positive_int(value.get("minimumCorrelationSampleCount"), "minimumCorrelationSampleCount")
        self._positive_int(value.get("maximumCorrelationAgeSeconds"), "maximumCorrelationAgeSeconds")
        if sleeve > 1.0 - reserve:
            raise ValueError("El sleeve máximo viola la reserva de efectivo.")
        semantics = value.get("semantics")
        required_semantics = {
            "referenceCapitalIsUserOwnedAllocationBase": True,
            "singleAssetExposureIsNotPortfolioWeight": True,
            "fullLongMeansFillInstrumentSleeveNotWholePortfolio": True,
            "reducedLongScalesInstrumentSleeveByFrozenEconomicContract": True,
            "sellTargetsZeroInstrumentWeight": True,
            "holdPreservesCurrentVerifiedWeight": True,
        }
        if semantics != required_semantics:
            raise ValueError("La semántica de capital/asignación fue modificada.")
        policy = value.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("La política carece de controles.")
        for field in (
            "codeDefaultTargetWeight",
            "codeDefaultCorrelationThreshold",
            "codeDefaultStalenessThreshold",
            "automaticTrading",
        ):
            if policy.get(field) is not False:
                raise ValueError(f"{field} debe permanecer false.")

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            policy = json.loads(str(row["policy_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("policy_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "policy_id": str(row["policy_id"]),
            "registered_at": str(row["registered_at"]),
            "policy": policy,
            "policy_fingerprint": str(row["policy_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _currency(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", normalized) is None:
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return normalized

    def _unit(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0 or result > 1.0:
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        return result

    def _open_unit(self, value: object, field: str) -> float:
        result = self._unit(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser mayor que cero.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("La política contiene valores no finitos/no serializables.") from exc

    def _fingerprint(self, value: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(value).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _aware(self, value: object, field: str) -> str:
        raw = self._text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()

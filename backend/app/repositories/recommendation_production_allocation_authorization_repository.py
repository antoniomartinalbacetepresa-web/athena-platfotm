from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationProductionAllocationAuthorizationRepository:
    """Append-only registry for human-authorized production allocations.

    This registry authorizes an allocation decision only. It never authorizes order
    routing or automatic trading and deliberately has no HTTP write endpoint.
    """

    ARTIFACT_VERSION = "athena-production-allocation-authorization-v1"

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_production_allocation_authorizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    authorization_id TEXT NOT NULL UNIQUE,
                    recommendation_authorization_fingerprint TEXT NOT NULL,
                    uncertainty_bound_action_candidate_fingerprint TEXT NOT NULL,
                    allocation_candidate_fingerprint TEXT NOT NULL UNIQUE,
                    portfolio_valuation_evidence_fingerprint TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    authorized_at TEXT NOT NULL,
                    authorization_json TEXT NOT NULL,
                    authorization_fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_production_allocation_recommendation
                ON athena_recommendation_production_allocation_authorizations(
                    recommendation_authorization_fingerprint, authorized_at
                );
                """
            )

    def register(self, *, authorization_draft: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        core = self._validated_draft(authorization_draft)
        authorized_at = datetime.now(timezone.utc).isoformat()
        unsigned = {**core, "authorizedAt": authorized_at}
        authorization_fingerprint = self._fingerprint(unsigned)
        authorization = {**unsigned, "authorizationFingerprint": authorization_fingerprint}
        serialized = self._serialize(authorization)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.connect() as connection:
            duplicate = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_allocation_authorizations
                WHERE authorization_id = ? OR allocation_candidate_fingerprint = ?
                """,
                (core["authorizationId"], core["allocationCandidateFingerprint"]),
            ).fetchone()
            if duplicate is not None:
                existing = self._row(duplicate)
                if existing is None:
                    raise RuntimeError("No se pudo recuperar la autorización existente.")
                if existing["authorization"] == authorization:
                    return existing
                raise ValueError("La asignación o authorizationId ya fue autorizado de forma inmutable.")

            connection.execute(
                """
                INSERT INTO athena_recommendation_production_allocation_authorizations (
                    authorization_id, recommendation_authorization_fingerprint,
                    uncertainty_bound_action_candidate_fingerprint,
                    allocation_candidate_fingerprint,
                    portfolio_valuation_evidence_fingerprint,
                    operator_id, authorized_at, authorization_json,
                    authorization_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    core["authorizationId"],
                    core["recommendationAuthorizationFingerprint"],
                    core["uncertaintyBoundActionCandidateFingerprint"],
                    core["allocationCandidateFingerprint"],
                    core["portfolioValuationEvidenceFingerprint"],
                    core["operatorId"], authorized_at, serialized,
                    authorization_fingerprint, created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_allocation_authorizations
                WHERE authorization_id = ?
                """,
                (core["authorizationId"],),
            ).fetchone()
        result = self._row(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la autorización registrada.")
        return result

    def get(self, *, authorization_id: str) -> dict[str, Any] | None:
        self.initialize()
        normalized = self._text(authorization_id, "authorization_id")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM athena_recommendation_production_allocation_authorizations
                WHERE authorization_id = ?
                """,
                (normalized,),
            ).fetchone()
        return self._row(row)

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("El registro de autorización de allocation debe ser objeto.")
        authorization = record.get("authorization")
        if not isinstance(authorization, dict):
            raise ValueError("El registro carece de authorization válida.")
        if authorization.get("authorizationId") != self._text(record.get("authorization_id"), "authorization_id"):
            raise ValueError("La autorización persistida cambió authorizationId.")
        for api_key, db_key in (
            ("recommendationAuthorizationFingerprint", "recommendation_authorization_fingerprint"),
            ("uncertaintyBoundActionCandidateFingerprint", "uncertainty_bound_action_candidate_fingerprint"),
            ("allocationCandidateFingerprint", "allocation_candidate_fingerprint"),
            ("portfolioValuationEvidenceFingerprint", "portfolio_valuation_evidence_fingerprint"),
        ):
            if authorization.get(api_key) != self._sha256(record.get(db_key), db_key):
                raise ValueError(f"La autorización persistida cambió {api_key}.")
        if authorization.get("operatorId") != self._text(record.get("operator_id"), "operator_id"):
            raise ValueError("La autorización persistida cambió operatorId.")
        authorized_at = self._aware_iso(record.get("authorized_at"), "authorized_at")
        created_at = self._aware_iso(record.get("created_at"), "created_at")
        if created_at < authorized_at:
            raise ValueError("created_at no puede preceder a authorized_at.")
        if self._aware_iso(authorization.get("authorizedAt"), "authorizedAt") != authorized_at:
            raise ValueError("La autorización persistida cambió authorizedAt.")
        supplied = self._sha256(record.get("authorization_fingerprint"), "authorization_fingerprint")
        if authorization.get("authorizationFingerprint") != supplied:
            raise ValueError("El fingerprint persistido no coincide con la autorización.")
        unsigned = dict(authorization)
        unsigned.pop("authorizationFingerprint", None)
        if self._fingerprint(unsigned) != supplied:
            raise ValueError("La autorización fue modificada después de persistirse.")
        self._validated_draft({
            key: value for key, value in authorization.items()
            if key not in {"authorizedAt", "authorizationFingerprint"}
        })
        return record

    def _validated_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("authorization_draft debe ser objeto.")
        if {"authorizedAt", "authorizationFingerprint"}.intersection(payload):
            raise ValueError("Los timestamps y fingerprints finales los genera el registro.")
        if payload.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de autorización de allocation no compatible.")
        if payload.get("status") != "production_allocation_authorized":
            raise ValueError("Estado de autorización de allocation inválido.")
        if payload.get("humanReviewConfirmed") is not True:
            raise ValueError("La autorización de allocation requiere revisión humana explícita.")
        if payload.get("authorizationMethod") != "offline_local_operator":
            raise ValueError("Sólo se admite autorización offline local.")
        if payload.get("advisoryStatus") != "production_allocation":
            raise ValueError("advisoryStatus de allocation productivo inválido.")
        if payload.get("productionEligible") is not True or payload.get("allocationEligible") is not True:
            raise ValueError("La autorización debe habilitar explícitamente producción y allocation.")
        for field in ("automaticAllocationPromotion", "executionEligible", "orderRoutingEligible", "automaticTrading"):
            if payload.get(field) is not False:
                raise ValueError(f"La autorización debe mantener {field}=False.")
        reference_capital = self._positive_finite(payload.get("referenceCapital"), "referenceCapital")
        target_amount = self._nonnegative_finite(payload.get("targetAmountInBaseCurrency"), "targetAmountInBaseCurrency")
        delta_amount = self._finite(payload.get("deltaAmountInBaseCurrency"), "deltaAmountInBaseCurrency")
        reason = self._text(payload.get("authorizationReason"), "authorizationReason")
        if len(reason) < 20:
            raise ValueError("authorizationReason debe documentar la decisión de gobierno.")
        allocation = payload.get("allocationCandidate")
        if not isinstance(allocation, dict):
            raise ValueError("La autorización debe sellar el candidato de allocation exacto.")
        allocation_fp = self._sha256(payload.get("allocationCandidateFingerprint"), "allocationCandidateFingerprint")
        if allocation.get("allocationCandidateFingerprint") != allocation_fp:
            raise ValueError("El candidato sellado no corresponde a allocationCandidateFingerprint.")
        for field in ("productionEligible", "allocationEligible", "automaticTrading"):
            if allocation.get(field) is not False:
                raise ValueError("El candidato fuente debe permanecer no productivo y no ejecutable.")
        if allocation.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato fuente debe permanecer no_advice.")
        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "authorizationId": self._text(payload.get("authorizationId"), "authorizationId"),
            "status": "production_allocation_authorized",
            "recommendationAuthorizationId": self._text(payload.get("recommendationAuthorizationId"), "recommendationAuthorizationId"),
            "recommendationAuthorizationFingerprint": self._sha256(payload.get("recommendationAuthorizationFingerprint"), "recommendationAuthorizationFingerprint"),
            "uncertaintyBoundActionCandidateFingerprint": self._sha256(payload.get("uncertaintyBoundActionCandidateFingerprint"), "uncertaintyBoundActionCandidateFingerprint"),
            "allocationCandidateFingerprint": allocation_fp,
            "verifiedAllocationPipelineFingerprint": self._sha256(payload.get("verifiedAllocationPipelineFingerprint"), "verifiedAllocationPipelineFingerprint"),
            "portfolioValuationEvidenceFingerprint": self._sha256(payload.get("portfolioValuationEvidenceFingerprint"), "portfolioValuationEvidenceFingerprint"),
            "economicContractFingerprint": self._sha256(payload.get("economicContractFingerprint"), "economicContractFingerprint"),
            "allocationPolicyId": self._text(payload.get("allocationPolicyId"), "allocationPolicyId"),
            "allocationPolicyFingerprint": self._sha256(payload.get("allocationPolicyFingerprint"), "allocationPolicyFingerprint"),
            "instrumentId": self._positive_int(payload.get("instrumentId"), "instrumentId"),
            "symbol": self._text(payload.get("symbol"), "symbol"),
            "asOf": self._aware_iso(payload.get("asOf"), "asOf"),
            "baseCurrency": self._currency(payload.get("baseCurrency"), "baseCurrency"),
            "action": self._action(payload.get("action")),
            "policyState": self._text(payload.get("policyState"), "policyState"),
            "referenceCapital": reference_capital,
            "targetAmountInBaseCurrency": target_amount,
            "deltaAmountInBaseCurrency": delta_amount,
            "correlationEvidenceFingerprints": self._fingerprint_list(payload.get("correlationEvidenceFingerprints")),
            "allocationCandidate": allocation,
            "operatorId": self._text(payload.get("operatorId"), "operatorId"),
            "authorizationReason": reason,
            "humanReviewConfirmed": True,
            "authorizationMethod": "offline_local_operator",
            "advisoryStatus": "production_allocation",
            "productionEligible": True,
            "allocationEligible": True,
            "automaticAllocationPromotion": False,
            "executionEligible": False,
            "orderRoutingEligible": False,
            "automaticTrading": False,
            "policy": {
                "networkWriteEndpointExposed": False,
                "humanAuthorizationRequired": True,
                "recommendationAuthorizationRequired": True,
                "authorizationDoesNotAuthorizeExecution": True,
                "automaticAllocationPromotion": False,
                "automaticTrading": False,
            },
        }

    def _row(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            authorization = json.loads(str(row["authorization_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("authorization_json persistido no es válido.") from exc
        record = {
            "id": int(row["id"]),
            "authorization_id": str(row["authorization_id"]),
            "recommendation_authorization_fingerprint": str(row["recommendation_authorization_fingerprint"]),
            "uncertainty_bound_action_candidate_fingerprint": str(row["uncertainty_bound_action_candidate_fingerprint"]),
            "allocation_candidate_fingerprint": str(row["allocation_candidate_fingerprint"]),
            "portfolio_valuation_evidence_fingerprint": str(row["portfolio_valuation_evidence_fingerprint"]),
            "operator_id": str(row["operator_id"]),
            "authorized_at": str(row["authorized_at"]),
            "authorization": authorization,
            "authorization_fingerprint": str(row["authorization_fingerprint"]),
            "created_at": str(row["created_at"]),
        }
        return self.validate_record(record)

    def _serialize(self, value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("La autorización contiene valores no serializables o no finitos.") from exc

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(self._serialize(payload).encode("utf-8")).hexdigest()

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _fingerprint_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("correlationEvidenceFingerprints debe ser lista.")
        result = [self._sha256(item, "correlationEvidenceFingerprint") for item in value]
        if len(result) != len(set(result)):
            raise ValueError("correlationEvidenceFingerprints contiene duplicados.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _action(self, value: object) -> str:
        result = self._text(value, "action").lower()
        if result not in {"buy", "hold", "reduce", "sell"}:
            raise ValueError("action no soportada.")
        return result

    def _currency(self, value: object, field: str) -> str:
        result = self._text(value, field).upper()
        if len(result) != 3 or not result.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _aware_iso(self, value: object, field: str) -> str:
        raw = self._text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc).isoformat()

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _nonnegative_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0:
            raise ValueError(f"{field} no puede ser negativo.")
        return result

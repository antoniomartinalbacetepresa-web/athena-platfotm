from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.recommendation_production_read_service import RecommendationProductionReadService


class _ProductionReadService(Protocol):
    def resolve_latest(self, *, as_of: datetime, symbol: str | None = None, instrument_id: int | None = None) -> dict[str, Any]: ...


class RecommendationProfessionalDossierService:
    """Read-only professional dossier built only from sealed production evidence."""

    PROFESSIONAL_MODULES = (
        "expectationsGap",
        "reverseValuation",
        "scenarioAsymmetry",
        "catalysts",
        "thesisInvalidation",
        "factorRisk",
        "performanceAttribution",
        "investmentJournal",
        "devilsAdvocate",
        "athenaRadar",
    )

    def __init__(self, *, production_read_service: _ProductionReadService | None = None) -> None:
        self._production_read_service = production_read_service or RecommendationProductionReadService()

    def build(self, *, as_of: datetime, symbol: str | None = None, instrument_id: int | None = None) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        state = self._production_read_service.resolve_latest(as_of=cutoff, symbol=symbol, instrument_id=instrument_id)
        self._assert_safe_state(state)
        recommendation = state.get("recommendation")
        allocation = state.get("allocation")
        modules = {
            name: {
                "status": "not_yet_evidenced",
                "productionEligible": False,
                "reason": "No existe todavía un artefacto PIT sellado y validado para este módulo.",
            }
            for name in self.PROFESSIONAL_MODULES
        }
        if recommendation is None:
            return {
                "status": "professional_dossier_no_production_recommendation",
                "asOf": cutoff.isoformat(),
                "symbol": state.get("symbol"),
                "instrumentId": state.get("instrumentId"),
                "decision": None,
                "evidence": {"productionRecommendationAuthorized": False, "productionAllocationAuthorized": False},
                "professionalModules": modules,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "allocationEligible": False,
                "executionEligible": False,
                "orderRoutingEligible": False,
                "automaticTrading": False,
                "readOnly": True,
            }
        if not isinstance(recommendation, dict):
            raise ValueError("La recomendación productiva no es un objeto válido.")
        expected_excess = recommendation.get("expectedExcessReturn")
        if expected_excess is not None:
            expected_excess = self._finite(expected_excess, "expectedExcessReturn")
        horizon = recommendation.get("horizonDays")
        if horizon is not None:
            if isinstance(horizon, bool):
                raise ValueError("horizonDays no es válido.")
            horizon = int(horizon)
            if horizon <= 0:
                raise ValueError("horizonDays debe ser positivo.")
        decision = {
            "instrumentId": recommendation.get("instrumentId"),
            "symbol": recommendation.get("symbol"),
            "action": recommendation.get("action"),
            "policyState": recommendation.get("policyState"),
            "horizonDays": horizon,
            "expectedExcessReturn": expected_excess,
            "authorizationReason": recommendation.get("authorizationReason"),
            "recommendationAuthorizationFingerprint": recommendation.get("authorizationFingerprint"),
            "economicContractFingerprint": recommendation.get("economicContractFingerprint"),
            "decisionAsOf": recommendation.get("asOf"),
            "authorizedAt": recommendation.get("authorizedAt"),
        }
        evidence = {
            "productionRecommendationAuthorized": True,
            "oosCalibrationBound": True,
            "promotedActionPolicyBound": True,
            "precommittedUncertaintyGateBound": True,
            "humanReviewBound": True,
            "productionAllocationAuthorized": allocation is not None,
            "expectedExcessReturnIsProbability": False,
            "expectedExcessReturnIsGuarantee": False,
        }
        if allocation is not None:
            if not isinstance(allocation, dict):
                raise ValueError("La autorización de allocation no es válida.")
            evidence["allocationExecutionEligible"] = False
            evidence["allocationOrderRoutingEligible"] = False
        return {
            "status": "professional_dossier_production_recommendation_available",
            "asOf": cutoff.isoformat(),
            "symbol": decision["symbol"],
            "instrumentId": decision["instrumentId"],
            "decision": decision,
            "evidence": evidence,
            "professionalModules": modules,
            "advisoryStatus": "production_recommendation",
            "productionEligible": True,
            "allocationEligible": allocation is not None,
            "executionEligible": False,
            "orderRoutingEligible": False,
            "automaticTrading": False,
            "readOnly": True,
        }

    def _assert_safe_state(self, state: object) -> None:
        if not isinstance(state, dict):
            raise ValueError("El estado productivo no es válido.")
        if state.get("automaticTrading") is not False or state.get("readOnly") is not True:
            raise ValueError("El estado productivo no cumple el contrato seguro de lectura.")
        recommendation = state.get("recommendation")
        allocation = state.get("allocation")
        if bool(state.get("productionRecommendationAvailable")) != (recommendation is not None):
            raise ValueError("El estado productivo contradice la disponibilidad de recomendación.")
        if bool(state.get("productionAllocationAvailable")) != (allocation is not None):
            raise ValueError("El estado productivo contradice la disponibilidad de allocation.")
        if allocation is not None and recommendation is None:
            raise ValueError("No puede existir allocation productivo sin recomendación productiva.")

    def _aware(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser numérico finito.")
        return result

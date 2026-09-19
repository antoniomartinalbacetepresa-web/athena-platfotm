from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol

from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


class _EconomicContractValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionEconomicUtilityService:
    """Evaluate hindsight counterfactual action utility under a frozen contract.

    The realized excess return is an outcome label, never a live feature. This
    service is therefore suitable only for training/evaluation research after an
    outcome has matured. It does not choose a live action and deliberately emits
    no single hindsight action when multiple actions tie.
    """

    ARTIFACT_VERSION = "shadow-action-economic-utility-v1"

    def __init__(
        self,
        *,
        economic_contract_validator: _EconomicContractValidator | None = None,
    ) -> None:
        self._economic_contract_validator = (
            economic_contract_validator or RecommendationShadowActionEconomicContractService()
        )

    def evaluate(
        self,
        *,
        economic_contract: dict[str, Any],
        current_state: str,
        realized_excess_return: float,
    ) -> dict[str, Any]:
        validated = self._economic_contract_validator.validate(economic_contract)
        if validated is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")
        realized = self._finite(realized_excess_return, "realized_excess_return")
        state = str(current_state or "").strip()

        states = economic_contract.get("positionStates")
        actions = economic_contract.get("actions")
        objective = economic_contract.get("economicObjective")
        if not isinstance(states, dict) or state not in states:
            raise ValueError("current_state no pertenece al contrato económico.")
        if not isinstance(actions, dict) or not isinstance(objective, dict):
            raise ValueError("El contrato económico está incompleto.")

        current_exposure = self._exposure(states[state], "current exposure")
        transaction_cost_bps = self._nonnegative_finite(
            objective.get("transactionCostBps"), "transactionCostBps"
        )
        slippage_bps = self._nonnegative_finite(
            objective.get("slippageBps"), "slippageBps"
        )
        friction_rate = (transaction_cost_bps + slippage_bps) / 10_000.0

        utilities: dict[str, Any] = {}
        best_utility: float | None = None
        best_actions: list[str] = []
        for action_name, action in actions.items():
            if not isinstance(action, dict):
                raise ValueError("La semántica de acción es inválida.")
            allowed_from = action.get("allowedFrom")
            if not isinstance(allowed_from, list):
                raise ValueError("allowedFrom debe ser una lista.")
            if state not in allowed_from:
                continue
            target_raw = action.get("targetExposureFraction")
            target_exposure = (
                current_exposure
                if target_raw == "unchanged"
                else self._unit_interval(target_raw, "targetExposureFraction")
            )
            exposure_change = target_exposure - current_exposure
            trading_friction = abs(exposure_change) * friction_rate
            gross_utility = target_exposure * realized
            net_utility = gross_utility - trading_friction
            utilities[action_name] = {
                "currentExposureFraction": current_exposure,
                "targetExposureFraction": target_exposure,
                "absoluteExposureChange": abs(exposure_change),
                "grossRealizedExcessUtility": gross_utility,
                "transactionAndSlippageCost": trading_friction,
                "netRealizedExcessUtility": net_utility,
            }
            if best_utility is None or net_utility > best_utility:
                best_utility = net_utility
                best_actions = [action_name]
            elif net_utility == best_utility:
                best_actions.append(action_name)

        if not utilities:
            raise ValueError("No hay acciones permitidas para current_state.")
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "economicContractFingerprint": self._sha256(
                economic_contract.get("economicContractFingerprint"),
                "economicContractFingerprint",
            ),
            "currentState": state,
            "currentExposureFraction": current_exposure,
            "realizedExcessReturn": realized,
            "allowedActionUtilities": utilities,
            "bestNetRealizedExcessUtility": best_utility,
            "hindsightBestActions": best_actions,
        }
        return {
            **core,
            "utilityFingerprint": self._fingerprint(core),
            "labelSemantics": "matured_outcome_hindsight_counterfactual_not_live_feature",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "action": None,
            "score": None,
            "conviction": None,
            "automaticTrading": False,
        }

    def _exposure(self, payload: object, field: str) -> float:
        if not isinstance(payload, dict) or set(payload) != {"targetExposureFraction"}:
            raise ValueError(f"{field} es inválida.")
        return self._unit_interval(payload.get("targetExposureFraction"), field)

    def _unit_interval(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0 or result > 1.0:
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        return result

    def _nonnegative_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0:
            raise ValueError(f"{field} debe ser no negativo.")
        return result

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

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

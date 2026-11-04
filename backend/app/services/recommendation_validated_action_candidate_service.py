from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.repositories.recommendation_action_promotion_decision_repository import (
    RecommendationActionPromotionDecisionRepository,
)
from app.repositories.recommendation_shadow_action_threshold_selection_repository import (
    RecommendationShadowActionThresholdSelectionRepository,
)
from app.services.recommendation_calibrated_live_candidate_service import (
    RecommendationCalibratedLiveCandidateService,
)
from app.services.recommendation_portfolio_policy_state_service import (
    RecommendationPortfolioPolicyStateService,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class RecommendationValidatedActionCandidateService:
    """Apply one exact promoted policy to one exact calibrated live signal.

    This produces an auditable action candidate only. It does not set
    productionEligible or authorize allocation/trading. The original live candidate
    remains the sole signal source; the calibrated artifact proves model identity;
    the persisted action decision proves OOS policy acceptance; and portfolio state
    must be explicit and identity-matched.
    """

    ARTIFACT_VERSION = "athena-validated-action-candidate-v1"

    def __init__(
        self,
        *,
        action_decision_repository: RecommendationActionPromotionDecisionRepository | None = None,
        selection_repository: RecommendationShadowActionThresholdSelectionRepository | None = None,
        live_candidate_service: RecommendationShadowLiveCandidateService | None = None,
        calibrated_candidate_service: RecommendationCalibratedLiveCandidateService | None = None,
        portfolio_state_service: RecommendationPortfolioPolicyStateService | None = None,
    ) -> None:
        self._decision_repository = action_decision_repository or RecommendationActionPromotionDecisionRepository()
        self._selection_repository = selection_repository or RecommendationShadowActionThresholdSelectionRepository()
        self._live_candidate_service = live_candidate_service or RecommendationShadowLiveCandidateService()
        self._calibrated_candidate_service = calibrated_candidate_service or RecommendationCalibratedLiveCandidateService()
        self._portfolio_state_service = portfolio_state_service or RecommendationPortfolioPolicyStateService()

    def build(
        self,
        *,
        action_decision_id: str,
        live_candidate: dict[str, Any],
        calibrated_candidate: dict[str, Any],
        portfolio_state: dict[str, Any],
        horizon_days: int,
    ) -> dict[str, Any]:
        if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days <= 0:
            raise ValueError("horizon_days debe ser entero positivo.")
        live = self._live_candidate_service.validate_artifact(live_candidate)
        calibrated = self._calibrated_candidate_service.validate_artifact(calibrated_candidate)
        state = self._portfolio_state_service.validate_artifact(portfolio_state)
        if live is not live_candidate or calibrated is not calibrated_candidate or state is not portfolio_state:
            raise ValueError("Un validador sustituyó un artefacto fuente.")

        if calibrated.get("candidateFingerprint") != live.get("candidateFingerprint"):
            raise ValueError("El candidato calibrado no pertenece al live candidate suministrado.")
        if calibrated.get("instrumentId") != live.get("instrumentId"):
            raise ValueError("El candidato calibrado cambió instrumentId.")
        if state.get("instrumentId") != live.get("instrumentId"):
            raise ValueError("El estado de cartera pertenece a otro instrumento.")

        record = self._decision_repository.get(decision_id=action_decision_id)
        if record is None:
            raise ValueError("La decisión de promoción de acciones no está registrada.")
        if self._decision_repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó la decisión de promoción.")
        decision = record.get("decision")
        if not isinstance(decision, dict) or decision.get("actionPromotionEvidenceAccepted") is not True:
            raise ValueError("La decisión no acepta evidencia de acciones.")
        self._assert_decision_non_productive(decision)

        key = str(horizon_days)
        live_horizons = live.get("horizons")
        calibrated_horizons = calibrated.get("horizons")
        if not isinstance(live_horizons, dict) or not isinstance(calibrated_horizons, dict):
            raise ValueError("Los candidatos carecen de horizons.")
        live_horizon = live_horizons.get(key)
        calibrated_horizon = calibrated_horizons.get(key)
        if not isinstance(live_horizon, dict) or not isinstance(calibrated_horizon, dict):
            raise ValueError("El horizonte solicitado no existe en el candidato.")
        signal = self._finite(live_horizon.get("expectedExcessReturn"), "expectedExcessReturn")
        model_fingerprint = self._sha256(live_horizon.get("modelFingerprint"), "modelFingerprint")
        if calibrated_horizon.get("calibrationEvidenceBound") is not True:
            raise ValueError("El horizonte no está ligado a calibración OOS.")
        if model_fingerprint != self._sha256(
            calibrated_horizon.get("modelFingerprint"), "calibrated.modelFingerprint"
        ):
            raise ValueError("El modelo live y el modelo calibrado no coinciden.")
        expected_model = decision.get("modelFingerprintsByHorizon", {}).get(key)
        if model_fingerprint != self._sha256(expected_model, "decision.modelFingerprint"):
            raise ValueError("El modelo live no coincide con la decisión de acciones.")

        selection_fingerprint = self._sha256(
            decision.get("selectionFingerprint"), "selectionFingerprint"
        )
        selection_record = self._selection_repository.get(
            selection_fingerprint=selection_fingerprint
        )
        if selection_record is None:
            raise ValueError("La selección congelada de acciones no está registrada.")
        if self._selection_repository.validate_record(selection_record) is not selection_record:
            raise ValueError("El repositorio sustituyó la selección congelada.")
        selection = selection_record.get("selection")
        if not isinstance(selection, dict):
            raise ValueError("La selección congelada carece de payload.")

        policy_state = str(state.get("policyState") or "")
        selected_horizon = selection.get("selections", {}).get(key)
        if not isinstance(selected_horizon, dict):
            raise ValueError("La selección no contiene el horizonte solicitado.")
        state_payload = selected_horizon.get("states", {}).get(policy_state)
        if not isinstance(state_payload, dict):
            raise ValueError("La selección no contiene el estado de cartera solicitado.")
        policy = state_payload.get("selectedPolicy")
        if not isinstance(policy, dict) or policy.get("currentState") != policy_state:
            raise ValueError("La política seleccionada no corresponde al estado de cartera.")
        policy_fingerprint = self._sha256(policy.get("policyFingerprint"), "policyFingerprint")
        expected_policy = (
            decision.get("policyFingerprintsByHorizonAndState", {})
            .get(key, {})
            .get(policy_state)
        )
        if policy_fingerprint != self._sha256(expected_policy, "decision.policyFingerprint"):
            raise ValueError("La política congelada no coincide con la decisión promovida.")

        action = self._decide(policy, signal)
        position_present = state.get("positionPresent") is True
        if action in {"reduce", "sell"} and not position_present:
            raise ValueError("reduce/sell requieren una posición real.")
        if policy_state == "flat" and action in {"reduce", "sell"}:
            raise ValueError("Una cartera flat no puede producir reduce/sell.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "candidateFingerprint": self._sha256(live.get("candidateFingerprint"), "candidateFingerprint"),
            "calibratedCandidateFingerprint": self._sha256(
                calibrated.get("calibratedCandidateFingerprint"), "calibratedCandidateFingerprint"
            ),
            "actionPromotionDecisionId": decision.get("decisionId"),
            "actionPromotionDecisionFingerprint": self._sha256(
                decision.get("decisionFingerprint"), "decisionFingerprint"
            ),
            "portfolioPolicyStateFingerprint": self._sha256(
                state.get("portfolioPolicyStateFingerprint"), "portfolioPolicyStateFingerprint"
            ),
            "instrumentId": live.get("instrumentId"),
            "symbol": live.get("symbol"),
            "asOf": live.get("asOf"),
            "horizonDays": horizon_days,
            "modelFingerprint": model_fingerprint,
            "policyState": policy_state,
            "policyFingerprint": policy_fingerprint,
            "expectedExcessReturn": signal,
            "action": action,
        }
        return {
            "status": "validated_action_candidate_non_advisory",
            **core,
            "validatedActionCandidateFingerprint": self._fingerprint(core),
            "actionEvidenceReady": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "liveSignalSource": "integrity_validated_live_candidate",
                "exactCalibratedModelRequired": True,
                "exactPromotedPolicyRequired": True,
                "portfolioStateMustBeExplicit": True,
                "reducedVsFullExposureInferredFromShares": False,
                "reduceOrSellRequiresPosition": True,
                "actionCandidateIsNotProductionAuthorization": True,
                "automaticTrading": False,
            },
        }

    def _decide(self, policy: dict[str, Any], signal: float) -> str:
        state = str(policy.get("currentState") or "")
        thresholds = policy.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("La política carece de thresholds.")
        if state == "flat":
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            return "buy" if signal >= buy else "hold"
        if state == "reduced_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            if not sell < buy:
                raise ValueError("La política reduced_long exige sell < buy.")
            if signal <= sell:
                return "sell"
            if signal >= buy:
                return "buy"
            return "hold"
        if state == "full_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            reduce = self._finite(thresholds.get("reduceAtOrBelow"), "reduceAtOrBelow")
            if not sell < reduce:
                raise ValueError("La política full_long exige sell < reduce.")
            if signal <= sell:
                return "sell"
            if signal <= reduce:
                return "reduce"
            return "hold"
        raise ValueError("Estado de política no soportado.")

    def _assert_decision_non_productive(self, decision: dict[str, Any]) -> None:
        if decision.get("advisoryStatus") != "no_advice":
            raise ValueError("La decisión debe mantener no_advice.")
        if decision.get("productionEligible") is not False:
            raise ValueError("La decisión de evidencia no puede habilitar producción.")
        if decision.get("recommendationCandidateReady") is not False:
            raise ValueError("La decisión de evidencia no puede habilitar recomendaciones.")
        if decision.get("automaticTrading") is not False:
            raise ValueError("La decisión debe mantener automaticTrading=False.")

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
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
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

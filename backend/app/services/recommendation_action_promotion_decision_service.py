from __future__ import annotations

from typing import Any

from app.repositories.recommendation_action_promotion_decision_repository import (
    RecommendationActionPromotionDecisionRepository,
)
from app.services.recommendation_model_bound_action_promotion_evidence_service import (
    RecommendationModelBoundActionPromotionEvidenceService,
)


class RecommendationActionPromotionDecisionService:
    """Persist one immutable acceptance decision for model-bound action evidence.

    This service intentionally stops before action emission. A persisted pass only
    proves that a frozen policy/model combination cleared its precommitted OOS gate.
    Portfolio state and a current calibrated candidate must still be bound later.
    """

    def __init__(
        self,
        *,
        evidence_service: RecommendationModelBoundActionPromotionEvidenceService | None = None,
        repository: RecommendationActionPromotionDecisionRepository | None = None,
    ) -> None:
        self._evidence_service = (
            evidence_service or RecommendationModelBoundActionPromotionEvidenceService()
        )
        self._repository = repository or RecommendationActionPromotionDecisionRepository()

    def decide_registered(
        self,
        *,
        decision_id: str,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
        model_identity_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = self._evidence_service.evaluate_registered(
            confirmation_artifact=confirmation_artifact,
            protocol_id=protocol_id,
            model_identity_attestation=model_identity_attestation,
        )
        if evidence.get("modelBoundActionPromotionEvidenceReady") is not True:
            raise ValueError(
                "La evidencia de política/modelo no supera el protocolo precomprometido."
            )
        if evidence.get("status") != "model_bound_action_promotion_evidence_ready":
            raise ValueError("El estado de evidencia model-bound es inconsistente.")
        self._assert_non_productive(evidence)
        record = self._repository.append(decision_id=decision_id, evidence=evidence)
        if self._repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó la decisión persistida.")
        decision = record.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("La decisión persistida carece de payload válido.")
        return {
            "status": "action_promotion_decision_persisted",
            "decisionId": decision.get("decisionId"),
            "decisionFingerprint": decision.get("decisionFingerprint"),
            "decidedAt": decision.get("decidedAt"),
            "modelBoundActionPromotionEvidenceFingerprint": decision.get(
                "modelBoundActionPromotionEvidenceFingerprint"
            ),
            "protocolId": decision.get("protocolId"),
            "protocolFingerprint": decision.get("protocolFingerprint"),
            "selectionFingerprint": decision.get("selectionFingerprint"),
            "confirmationFingerprint": decision.get("confirmationFingerprint"),
            "economicContractFingerprint": decision.get("economicContractFingerprint"),
            "requiredHorizons": decision.get("requiredHorizons"),
            "modelFingerprintsByHorizon": decision.get("modelFingerprintsByHorizon"),
            "policyFingerprintsByHorizonAndState": decision.get(
                "policyFingerprintsByHorizonAndState"
            ),
            "actionPromotionEvidenceAccepted": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "allocation": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "decisionIsAppendOnly": True,
                "exactModelAndPolicyIdentityPersisted": True,
                "currentCalibratedCandidateStillRequired": True,
                "portfolioStateStillRequired": True,
                "reduceOrSellWithoutPositionAllowed": False,
                "automaticTrading": False,
            },
        }

    def _assert_non_productive(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La evidencia debe mantener advisoryStatus=no_advice.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La evidencia no puede habilitar recomendaciones.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La evidencia no puede habilitar producción.")
        if payload.get("action") is not None:
            raise ValueError("La evidencia no puede contener action.")
        if payload.get("automaticTrading") is not False:
            raise ValueError("La evidencia debe mantener automaticTrading=False.")

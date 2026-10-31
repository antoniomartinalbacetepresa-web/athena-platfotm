from __future__ import annotations

from datetime import datetime
from typing import Any

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)
from app.services.recommendation_shadow_outcome_service import (
    RecommendationShadowOutcomeService,
)


class RecommendationShadowLiveFollowupService:
    """Mature PIT outcomes, then score immutable shadow live predictions."""

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        candidate_repository: RecommendationShadowLiveCandidateRepository | None = None,
        outcome_service: RecommendationShadowOutcomeService | None = None,
        evaluation_service: RecommendationShadowLiveCandidateEvaluationService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._outcome_service = outcome_service or RecommendationShadowOutcomeService()
        self._evaluation_service = (
            evaluation_service or RecommendationShadowLiveCandidateEvaluationService()
        )

    def run(
        self,
        *,
        candidate_id: int,
        as_of: datetime,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        if candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        stored = self._candidate_repository.get(candidate_id)
        if stored is None:
            raise ValueError("El candidato shadow live no existe.")
        snapshot_id = int(stored.get("snapshot_id", 0))
        if snapshot_id <= 0:
            raise ValueError("El candidato shadow live carece de snapshot_id válido.")

        outcome_progress = self._outcome_service.evaluate_snapshot(
            snapshot_id=snapshot_id,
            as_of=as_of,
            horizons=horizons,
        )
        self._assert_outcome_shadow(outcome_progress)

        evaluation = self._evaluation_service.evaluate(
            candidate_id=candidate_id,
            as_of=as_of,
        )
        self._assert_evaluation_shadow(evaluation)
        if int(evaluation.get("snapshotId", 0)) != snapshot_id:
            raise RuntimeError("La evaluación live cambió el snapshot de referencia.")

        return {
            "status": "shadow_live_followup_completed",
            "candidateId": candidate_id,
            "snapshotId": snapshot_id,
            "asOf": evaluation.get("asOf"),
            "outcomeProgress": outcome_progress,
            "predictionEvaluation": evaluation,
            "evaluatedHorizonCount": evaluation.get("evaluatedHorizonCount", 0),
            "metrics": evaluation.get("metrics"),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "outcomeMaturation": "existing_shadow_point_in_time_outcome_service",
                "benchmark": "frozen_on_snapshot_and_resolved_without_lookahead",
                "prediction": "immutable_persisted_shadow_live_candidate",
                "learning": "measurement_only_no_automatic_parameter_update",
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _assert_outcome_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El outcome shadow violó advisoryStatus=no_advice.")
        if payload.get("productionEligible") is True:
            raise ValueError("El outcome shadow intentó habilitar producción.")

    def _assert_evaluation_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La evaluación shadow violó advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La evaluación shadow debe declarar productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La evaluación shadow no puede habilitar recomendaciones.")

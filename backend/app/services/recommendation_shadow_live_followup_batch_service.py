from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_live_followup_service import (
    RecommendationShadowLiveFollowupService,
)


class RecommendationShadowLiveFollowupBatchService:
    """Advance every persisted live-shadow candidate using one PIT cutoff.

    This service intentionally does not decide whether ATHENA should trade or
    promote a model. It only asks the existing follow-up service to mature
    outcomes that are legitimately available at ``as_of`` and to score the
    immutable predictions against those outcomes.
    """

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        candidate_repository: RecommendationShadowLiveCandidateRepository | None = None,
        followup_service: RecommendationShadowLiveFollowupService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._followup_service = followup_service or RecommendationShadowLiveFollowupService(
            candidate_repository=self._candidate_repository
        )

    def run(
        self,
        *,
        as_of: datetime,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        effective_horizons = self._validated_horizons(horizons)
        candidates = self._candidate_repository.list_all()

        followups: list[dict[str, Any]] = []
        total_evaluated_horizons = 0
        candidates_with_evaluated_outcomes = 0
        candidates_pending = 0

        for stored in candidates:
            candidate_id = self._positive_int(stored.get("id"), "candidate.id")
            result = self._followup_service.run(
                candidate_id=candidate_id,
                as_of=cutoff,
                horizons=effective_horizons,
            )
            self._assert_shadow_contract(result)
            if int(result.get("candidateId", 0)) != candidate_id:
                raise RuntimeError("El seguimiento devolvió otro candidateId.")

            evaluated_count = self._non_negative_int(
                result.get("evaluatedHorizonCount", 0),
                "followup.evaluatedHorizonCount",
            )
            total_evaluated_horizons += evaluated_count
            if evaluated_count > 0:
                candidates_with_evaluated_outcomes += 1
            else:
                candidates_pending += 1
            followups.append(result)

        return {
            "status": "shadow_live_followup_batch_completed",
            "asOf": cutoff.isoformat(),
            "candidateCount": len(candidates),
            "processedCandidateCount": len(followups),
            "candidatesWithEvaluatedOutcomes": candidates_with_evaluated_outcomes,
            "candidatesPendingOutcomes": candidates_pending,
            "evaluatedHorizonCount": total_evaluated_horizons,
            "horizons": list(effective_horizons),
            "followups": followups,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "candidateDiscovery": "all_persisted_shadow_live_candidates_deterministic_order",
                "outcomeMaturation": "existing_point_in_time_followup_service",
                "lookAhead": "single_aware_as_of_cutoff_for_entire_batch",
                "learning": "measurement_only_no_automatic_parameter_update",
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _validated_horizons(self, horizons: tuple[int, ...]) -> tuple[int, ...]:
        if not isinstance(horizons, tuple) or not horizons:
            raise ValueError("horizons debe ser una tupla no vacía.")
        result: list[int] = []
        seen: set[int] = set()
        for raw in horizons:
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise ValueError("Todos los horizontes deben ser enteros positivos.")
            if raw in seen:
                raise ValueError("Los horizontes no pueden repetirse.")
            seen.add(raw)
            result.append(raw)
        return tuple(result)

    def _assert_shadow_contract(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El seguimiento live violó advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El seguimiento live intentó habilitar producción.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El seguimiento live intentó habilitar recomendaciones.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El seguimiento live carece de política válida.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El seguimiento live intentó promover producción automáticamente.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El seguimiento live intentó habilitar trading automático.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser un entero positivo.")
        return value

    def _non_negative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} debe ser un entero no negativo.")
        return value

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_multi_horizon_service import (
    RecommendationShadowMultiHorizonService,
)
from app.services.recommendation_shadow_walk_forward_plan_service import (
    RecommendationShadowWalkForwardPlanService,
)


class RecommendationShadowAutoWalkForwardService:
    """Plan and evaluate PIT walk-forward evidence across target horizons.

    This closes the gap between the persisted calibration dataset and the
    existing multi-horizon evaluator: folds are generated from real feature
    timestamps, purged before use, and then passed to the diagnostic evaluator.
    No successful result from this service is an investment recommendation.
    """

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        plan_service: RecommendationShadowWalkForwardPlanService | None = None,
        multi_horizon_service: RecommendationShadowMultiHorizonService | None = None,
        minimum_folds_per_horizon: int = 3,
    ) -> None:
        if minimum_folds_per_horizon < 2:
            raise ValueError("minimum_folds_per_horizon debe ser al menos 2.")
        self._plan_service = (
            plan_service
            if plan_service is not None
            else RecommendationShadowWalkForwardPlanService()
        )
        self._multi_horizon_service = (
            multi_horizon_service
            if multi_horizon_service is not None
            else RecommendationShadowMultiHorizonService()
        )
        self._minimum_folds_per_horizon = int(minimum_folds_per_horizon)

    def evaluate(
        self,
        *,
        as_of: datetime,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        normalized_horizons = self._validate_horizons(horizons)

        plans: dict[str, dict[str, Any]] = {}
        folds_by_horizon: dict[int, list[dict[str, datetime]]] = {}
        for horizon in normalized_horizons:
            plan = self._plan_service.build(
                as_of=cutoff,
                horizon_days=horizon,
                require_benchmark=True,
            )
            folds = list(plan.get("folds", []))
            plans[str(horizon)] = self._public_plan(plan)
            if len(folds) >= self._minimum_folds_per_horizon:
                folds_by_horizon[horizon] = folds

        evaluation = self._multi_horizon_service.evaluate(
            folds_by_horizon=folds_by_horizon,
            horizons=normalized_horizons,
        )

        return {
            "status": "shadow_auto_walk_forward_evaluated",
            "asOf": cutoff.isoformat(),
            "requestedHorizons": list(normalized_horizons),
            "minimumFoldsPerHorizon": self._minimum_folds_per_horizon,
            "plannedHorizonCount": sum(
                1
                for plan in plans.values()
                if int(plan.get("readyFoldCount", 0)) >= self._minimum_folds_per_horizon
            ),
            "plans": plans,
            "evaluation": evaluation,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "foldGeneration": "automatic_from_point_in_time_feature_timestamps",
                "foldAcceptance": "purged_counts_must_meet_minimums",
                "horizonEvaluation": "independent",
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "productionEligibility": False,
            },
        }

    def _public_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        # Datetime fold objects are an internal hand-off to the evaluator. The
        # outward diagnostic keeps only serialized boundaries and counts.
        return {
            key: value
            for key, value in plan.items()
            if key != "folds"
        }

    def _validate_horizons(self, horizons: tuple[int, ...]) -> tuple[int, ...]:
        if not horizons:
            raise ValueError("Se requiere al menos un horizonte.")
        normalized = tuple(int(value) for value in horizons)
        if any(value <= 0 for value in normalized):
            raise ValueError("Todos los horizontes deben ser positivos.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Los horizontes no pueden repetirse.")
        return normalized

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

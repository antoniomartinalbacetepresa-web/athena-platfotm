from __future__ import annotations

from typing import Any

from app.services.recommendation_shadow_walk_forward_service import (
    RecommendationShadowWalkForwardService,
)


class RecommendationShadowMultiHorizonService:
    """Aggregate walk-forward diagnostics across ATHENA's target horizons.

    The result is research evidence only. A strong result on one horizon cannot
    silently compensate for missing evidence on another, and no action labels or
    production eligibility are emitted here.
    """

    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        walk_forward_service: RecommendationShadowWalkForwardService | None = None,
        minimum_evaluated_horizons: int = 3,
    ) -> None:
        if minimum_evaluated_horizons <= 0:
            raise ValueError("minimum_evaluated_horizons debe ser positivo.")
        self._walk_forward_service = (
            walk_forward_service
            if walk_forward_service is not None
            else RecommendationShadowWalkForwardService()
        )
        self._minimum_evaluated_horizons = int(minimum_evaluated_horizons)

    def evaluate(
        self,
        *,
        folds_by_horizon: dict[int, list[dict[str, Any]]],
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        normalized_horizons = self._validate_horizons(horizons)
        horizon_results: dict[str, dict[str, Any]] = {}

        for horizon in normalized_horizons:
            folds = folds_by_horizon.get(horizon)
            if not folds:
                horizon_results[str(horizon)] = {
                    "status": "missing_walk_forward_folds",
                    "horizonDays": horizon,
                    "productionEligible": False,
                }
                continue
            horizon_results[str(horizon)] = self._walk_forward_service.evaluate(
                folds=folds,
                horizon_days=horizon,
            )

        evaluated = [
            result
            for result in horizon_results.values()
            if result.get("status") == "shadow_walk_forward_evaluated"
        ]
        stable = [
            result
            for result in evaluated
            if bool(result.get("summary", {}).get("stableDirectionally"))
        ]
        evaluated_count = len(evaluated)
        stable_count = len(stable)
        coverage_ratio = evaluated_count / len(normalized_horizons)
        stability_ratio = stable_count / evaluated_count if evaluated_count else 0.0

        status = (
            "shadow_multi_horizon_evaluated"
            if evaluated_count >= self._minimum_evaluated_horizons
            else "insufficient_multi_horizon_evidence"
        )

        return {
            "status": status,
            "requestedHorizons": list(normalized_horizons),
            "evaluatedHorizonCount": evaluated_count,
            "stableHorizonCount": stable_count,
            "minimumEvaluatedHorizons": self._minimum_evaluated_horizons,
            "coverageRatio": coverage_ratio,
            "stabilityRatioAcrossEvaluatedHorizons": stability_ratio,
            "horizons": horizon_results,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "horizons": "evaluated_independently",
                "missingEvidence": "never_imputed_as_success",
                "stability": "diagnostic_only_not_a_promotion_rule",
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "productionEligibility": False,
            },
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

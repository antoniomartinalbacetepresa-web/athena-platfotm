from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.services.recommendation_shadow_linear_candidate_service import (
    RecommendationShadowLinearCandidateService,
)


class RecommendationShadowWalkForwardService:
    """Evaluate one shadow candidate across ordered purged temporal folds.

    This service is diagnostic only. It never maps model outputs to actions and
    never promotes a model to production. Its purpose is to expose whether an
    apparent out-of-sample edge survives multiple later temporal windows rather
    than a single convenient train/validation/test split.
    """

    def __init__(
        self,
        *,
        candidate_service: RecommendationShadowLinearCandidateService | None = None,
        minimum_evaluated_folds: int = 3,
    ) -> None:
        if minimum_evaluated_folds < 2:
            raise ValueError("minimum_evaluated_folds debe ser al menos 2.")
        self._candidate_service = (
            candidate_service
            if candidate_service is not None
            else RecommendationShadowLinearCandidateService()
        )
        self._minimum_evaluated_folds = int(minimum_evaluated_folds)

    def evaluate(
        self,
        *,
        folds: list[dict[str, datetime]],
        horizon_days: int,
    ) -> dict[str, Any]:
        if horizon_days <= 0:
            raise ValueError("horizon_days debe ser positivo.")
        normalized = self._validate_folds(folds)

        results: list[dict[str, Any]] = []
        for index, fold in enumerate(normalized):
            evaluation = self._candidate_service.evaluate(
                as_of=fold["as_of"],
                train_end=fold["train_end"],
                validation_end=fold["validation_end"],
                horizon_days=horizon_days,
            )
            results.append(
                {
                    "foldIndex": index,
                    "boundaries": {
                        "trainEnd": fold["train_end"].isoformat(),
                        "validationEnd": fold["validation_end"].isoformat(),
                        "testEnd": fold["as_of"].isoformat(),
                    },
                    "evaluation": evaluation,
                }
            )

        evaluated = [
            item
            for item in results
            if item["evaluation"].get("status") == "shadow_linear_candidate_evaluated"
        ]
        blocked = len(results) - len(evaluated)
        if len(evaluated) < self._minimum_evaluated_folds:
            return {
                "status": "insufficient_walk_forward_evidence",
                "horizonDays": horizon_days,
                "foldCount": len(results),
                "evaluatedFoldCount": len(evaluated),
                "blockedFoldCount": blocked,
                "minimumEvaluatedFolds": self._minimum_evaluated_folds,
                "folds": results,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": self._policy(),
            }

        fold_metrics = []
        for item in evaluated:
            evaluation = item["evaluation"]
            test = evaluation["test"]
            baseline = evaluation["zeroExcessReturnBaseline"]
            baseline_mse = float(baseline["mse"])
            model_mse = float(test["mse"])
            improvement = (
                (baseline_mse - model_mse) / baseline_mse
                if baseline_mse > 0
                else 0.0
            )
            fold_metrics.append(
                {
                    "foldIndex": item["foldIndex"],
                    "mse": model_mse,
                    "mae": float(test["mae"]),
                    "signAccuracy": float(test["signAccuracy"]),
                    "baselineMse": baseline_mse,
                    "relativeMseImprovement": improvement,
                    "beatsZeroBaselineOnMse": model_mse < baseline_mse,
                }
            )

        win_count = sum(1 for metric in fold_metrics if metric["beatsZeroBaselineOnMse"])
        improvements = [metric["relativeMseImprovement"] for metric in fold_metrics]
        sign_accuracies = [metric["signAccuracy"] for metric in fold_metrics]
        mses = [metric["mse"] for metric in fold_metrics]
        maes = [metric["mae"] for metric in fold_metrics]
        win_rate = win_count / len(fold_metrics)
        median_improvement = float(median(improvements))
        median_sign_accuracy = float(median(sign_accuracies))

        # These are descriptive diagnostics, not production promotion thresholds.
        # Keeping them separate prevents a provisional research heuristic from
        # becoming an investment decision rule by accident.
        stable_directionally = win_rate >= (2.0 / 3.0) and median_improvement > 0

        return {
            "status": "shadow_walk_forward_evaluated",
            "horizonDays": horizon_days,
            "foldCount": len(results),
            "evaluatedFoldCount": len(evaluated),
            "blockedFoldCount": blocked,
            "foldMetrics": fold_metrics,
            "summary": {
                "baselineWinRate": win_rate,
                "medianRelativeMseImprovement": median_improvement,
                "medianSignAccuracy": median_sign_accuracy,
                "medianMse": float(median(mses)),
                "medianMae": float(median(maes)),
                "minimumRelativeMseImprovement": min(improvements),
                "maximumRelativeMseImprovement": max(improvements),
                "stableDirectionally": stable_directionally,
            },
            "folds": results,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def _validate_folds(
        self,
        folds: list[dict[str, datetime]],
    ) -> list[dict[str, datetime]]:
        if len(folds) < 2:
            raise ValueError("Se requieren al menos dos folds walk-forward.")
        normalized: list[dict[str, datetime]] = []
        previous_as_of: datetime | None = None
        for index, fold in enumerate(folds):
            try:
                train_end = self._aware_utc(fold["train_end"], f"folds[{index}].train_end")
                validation_end = self._aware_utc(
                    fold["validation_end"], f"folds[{index}].validation_end"
                )
                as_of = self._aware_utc(fold["as_of"], f"folds[{index}].as_of")
            except KeyError as exc:
                raise ValueError(f"Falta una frontera obligatoria en folds[{index}].") from exc
            if not train_end < validation_end < as_of:
                raise ValueError(
                    f"folds[{index}] requiere train_end < validation_end < as_of."
                )
            if previous_as_of is not None and as_of <= previous_as_of:
                raise ValueError("Los folds deben avanzar estrictamente en el tiempo por as_of.")
            previous_as_of = as_of
            normalized.append(
                {
                    "train_end": train_end,
                    "validation_end": validation_end,
                    "as_of": as_of,
                }
            )
        return normalized

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _policy(self) -> dict[str, Any]:
        return {
            "evaluation": "multiple_ordered_purged_temporal_folds",
            "benchmark": "zero_excess_return_baseline_per_fold",
            "stability": "reported_diagnostically_not_used_for_promotion",
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "productionEligibility": False,
        }

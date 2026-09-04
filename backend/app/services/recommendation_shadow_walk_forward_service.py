from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.services.recommendation_shadow_linear_candidate_service import (
    RecommendationShadowLinearCandidateService,
)
from app.services.recommendation_shadow_macro_fold_preprocessing_service import (
    RecommendationShadowMacroFoldPreprocessingService,
)
from app.services.recommendation_shadow_temporal_split_service import (
    RecommendationShadowTemporalSplitService,
)


class RecommendationShadowWalkForwardService:
    """Evaluate one shadow candidate across ordered purged temporal folds.

    Each fold is built exactly once, then reused by every research consumer.
    Macro preprocessing is fitted only on the frozen fold's training partition
    and remains diagnostic: macro values are not appended to the candidate model
    here and cannot silently influence scores, actions, or production eligibility.
    """

    def __init__(
        self,
        *,
        candidate_service: RecommendationShadowLinearCandidateService | None = None,
        split_service: RecommendationShadowTemporalSplitService | None = None,
        macro_preprocessing_service: RecommendationShadowMacroFoldPreprocessingService
        | None = None,
        minimum_evaluated_folds: int = 3,
    ) -> None:
        if minimum_evaluated_folds < 2:
            raise ValueError("minimum_evaluated_folds debe ser al menos 2.")
        self._candidate_service = (
            candidate_service
            if candidate_service is not None
            else RecommendationShadowLinearCandidateService()
        )
        self._split_service = (
            split_service
            if split_service is not None
            else RecommendationShadowTemporalSplitService()
        )
        self._macro_preprocessing_service = (
            macro_preprocessing_service
            if macro_preprocessing_service is not None
            else RecommendationShadowMacroFoldPreprocessingService()
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
            split = self._split_service.build(
                as_of=fold["as_of"],
                train_end=fold["train_end"],
                validation_end=fold["validation_end"],
                horizon_days=horizon_days,
                require_benchmark=True,
            )
            macro_preprocessing = self._macro_preprocessing_service.fit_transform(
                train_rows=list(split["train"]),
                validation_rows=list(split["validation"]),
                test_rows=list(split["test"]),
            )
            evaluation = self._candidate_service.evaluate_frozen_split(split=split)
            results.append(
                {
                    "foldIndex": index,
                    "boundaries": {
                        "trainEnd": fold["train_end"].isoformat(),
                        "validationEnd": fold["validation_end"].isoformat(),
                        "testEnd": fold["as_of"].isoformat(),
                    },
                    "macroResearch": {
                        "status": macro_preprocessing.get("status"),
                        "schemaVersion": macro_preprocessing.get("schemaVersion"),
                        "selectedFeatures": list(
                            macro_preprocessing.get("selectedFeatures") or []
                        ),
                        "fitParameters": dict(
                            macro_preprocessing.get("fitParameters") or {}
                        ),
                        "partitionCounts": {
                            name: len(
                                (macro_preprocessing.get("partitions") or {}).get(name)
                                or []
                            )
                            for name in ("train", "validation", "test")
                        },
                        "reason": macro_preprocessing.get("reason"),
                        "candidateInfluence": False,
                        "productionEligible": False,
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
                train_end = self._aware_utc(
                    fold["train_end"], f"folds[{index}].train_end"
                )
                validation_end = self._aware_utc(
                    fold["validation_end"], f"folds[{index}].validation_end"
                )
                as_of = self._aware_utc(fold["as_of"], f"folds[{index}].as_of")
            except KeyError as exc:
                raise ValueError(
                    f"Falta una frontera obligatoria en folds[{index}]."
                ) from exc
            if not train_end < validation_end < as_of:
                raise ValueError(
                    f"folds[{index}] requiere train_end < validation_end < as_of."
                )
            if previous_as_of is not None and as_of <= previous_as_of:
                raise ValueError(
                    "Los folds deben avanzar estrictamente en el tiempo por as_of."
                )
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
            "foldUniverse": "single_frozen_split_reused_by_all_fold_consumers",
            "benchmark": "zero_excess_return_baseline_per_fold",
            "stability": "reported_diagnostically_not_used_for_promotion",
            "macroResearchPreprocessing": "fit_inside_each_fold_train_only",
            "macroCandidateInfluence": "disabled_until_oos_comparison_is_validated",
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "productionEligibility": False,
        }

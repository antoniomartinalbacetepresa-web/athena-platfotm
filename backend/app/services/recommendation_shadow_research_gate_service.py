from __future__ import annotations

import math
from typing import Any


class RecommendationShadowResearchGateService:
    """Decide whether shadow evidence may advance to action-calibration research.

    Passing this gate is deliberately *not* production approval. The gate reads
    out-of-sample walk-forward metrics, so using them for candidate selection
    consumes them as research evidence. A candidate that passes must therefore
    be challenged on fresh, untouched evidence before any production decision.
    """

    def __init__(
        self,
        *,
        minimum_evaluated_horizons: int = 3,
        minimum_passing_horizons: int = 2,
        minimum_evaluated_folds_per_horizon: int = 3,
        minimum_horizon_pass_ratio: float = 2.0 / 3.0,
        minimum_fold_baseline_win_rate: float = 2.0 / 3.0,
        minimum_median_relative_mse_improvement: float = 0.0,
        minimum_median_sign_accuracy: float = 0.5,
        maximum_blocked_fold_ratio: float = 0.25,
    ) -> None:
        if minimum_evaluated_horizons <= 0 or minimum_passing_horizons <= 0:
            raise ValueError("Los mínimos de horizontes deben ser positivos.")
        if minimum_evaluated_folds_per_horizon < 2:
            raise ValueError("minimum_evaluated_folds_per_horizon debe ser al menos 2.")
        if minimum_passing_horizons > minimum_evaluated_horizons:
            raise ValueError(
                "minimum_passing_horizons no puede superar minimum_evaluated_horizons."
            )
        for name, value in (
            ("minimum_horizon_pass_ratio", minimum_horizon_pass_ratio),
            ("minimum_fold_baseline_win_rate", minimum_fold_baseline_win_rate),
            ("minimum_median_sign_accuracy", minimum_median_sign_accuracy),
            ("maximum_blocked_fold_ratio", maximum_blocked_fold_ratio),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} debe estar entre 0 y 1.")
        if not math.isfinite(minimum_median_relative_mse_improvement):
            raise ValueError("minimum_median_relative_mse_improvement debe ser finito.")

        self._minimum_evaluated_horizons = int(minimum_evaluated_horizons)
        self._minimum_passing_horizons = int(minimum_passing_horizons)
        self._minimum_evaluated_folds_per_horizon = int(
            minimum_evaluated_folds_per_horizon
        )
        self._minimum_horizon_pass_ratio = float(minimum_horizon_pass_ratio)
        self._minimum_fold_baseline_win_rate = float(minimum_fold_baseline_win_rate)
        self._minimum_median_relative_mse_improvement = float(
            minimum_median_relative_mse_improvement
        )
        self._minimum_median_sign_accuracy = float(minimum_median_sign_accuracy)
        self._maximum_blocked_fold_ratio = float(maximum_blocked_fold_ratio)

    def evaluate(self, *, multi_horizon_evidence: dict[str, Any]) -> dict[str, Any]:
        if bool(multi_horizon_evidence.get("productionEligible")):
            raise ValueError("La evidencia shadow no puede llegar marcada como productionEligible.")

        raw_horizons = multi_horizon_evidence.get("horizons")
        if not isinstance(raw_horizons, dict):
            raise ValueError("multi_horizon_evidence.horizons es obligatorio.")

        horizon_checks: dict[str, dict[str, Any]] = {}
        evaluated_count = 0
        passing_count = 0
        for horizon_key, evidence in raw_horizons.items():
            check = self._check_horizon(str(horizon_key), evidence)
            horizon_checks[str(horizon_key)] = check
            if check["evaluated"]:
                evaluated_count += 1
            if check["passesResearchGate"]:
                passing_count += 1

        pass_ratio = passing_count / evaluated_count if evaluated_count else 0.0
        global_reasons: list[str] = []
        if evaluated_count < self._minimum_evaluated_horizons:
            global_reasons.append("insufficient_evaluated_horizons")
        if passing_count < self._minimum_passing_horizons:
            global_reasons.append("insufficient_passing_horizons")
        if evaluated_count and pass_ratio < self._minimum_horizon_pass_ratio:
            global_reasons.append("insufficient_horizon_pass_ratio")

        research_stage_eligible = not global_reasons
        status = (
            "shadow_candidate_may_enter_action_calibration_research"
            if research_stage_eligible
            else (
                "insufficient_shadow_research_evidence"
                if evaluated_count < self._minimum_evaluated_horizons
                else "shadow_candidate_fails_research_gate"
            )
        )

        return {
            "status": status,
            "evaluatedHorizonCount": evaluated_count,
            "passingHorizonCount": passing_count,
            "horizonPassRatio": pass_ratio,
            "researchStageEligible": research_stage_eligible,
            "nextResearchStage": (
                "action_threshold_calibration_with_fresh_holdout_reserved"
                if research_stage_eligible
                else "continue_shadow_evidence_collection_or_candidate_revision"
            ),
            "globalReasons": global_reasons,
            "horizons": horizon_checks,
            "thresholds": self._thresholds(),
            "thresholdStatus": "provisional_research_only",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "passingMeaning": "eligible_only_for_next_research_stage",
                "testEvidenceAfterGate": "consumed_for_candidate_selection",
                "freshUntouchedHoldoutBeforeProduction": True,
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "productionEligibility": False,
            },
        }

    def _check_horizon(self, horizon: str, evidence: object) -> dict[str, Any]:
        if not isinstance(evidence, dict) or evidence.get("status") != "shadow_walk_forward_evaluated":
            return {
                "horizonDays": self._safe_horizon(horizon),
                "evaluated": False,
                "passesResearchGate": False,
                "reasons": ["walk_forward_not_evaluated"],
            }
        if bool(evidence.get("productionEligible")):
            raise ValueError(
                f"El horizonte {horizon} no puede estar marcado como productionEligible."
            )

        fold_count = self._non_negative_int(evidence.get("foldCount"), "foldCount")
        evaluated_folds = self._non_negative_int(
            evidence.get("evaluatedFoldCount"), "evaluatedFoldCount"
        )
        blocked_folds = self._non_negative_int(
            evidence.get("blockedFoldCount"), "blockedFoldCount"
        )
        if evaluated_folds + blocked_folds != fold_count:
            raise ValueError(
                f"El horizonte {horizon} tiene conteos de folds inconsistentes."
            )
        blocked_ratio = blocked_folds / fold_count if fold_count else 1.0

        summary = evidence.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"El horizonte {horizon} no contiene summary válido.")
        baseline_win_rate = self._finite_float(
            summary.get("baselineWinRate"), "baselineWinRate"
        )
        median_improvement = self._finite_float(
            summary.get("medianRelativeMseImprovement"),
            "medianRelativeMseImprovement",
        )
        median_sign_accuracy = self._finite_float(
            summary.get("medianSignAccuracy"), "medianSignAccuracy"
        )
        if not 0.0 <= baseline_win_rate <= 1.0:
            raise ValueError("baselineWinRate debe estar entre 0 y 1.")
        if not 0.0 <= median_sign_accuracy <= 1.0:
            raise ValueError("medianSignAccuracy debe estar entre 0 y 1.")

        reasons: list[str] = []
        if evaluated_folds < self._minimum_evaluated_folds_per_horizon:
            reasons.append("insufficient_evaluated_folds_for_research_gate")
        if baseline_win_rate < self._minimum_fold_baseline_win_rate:
            reasons.append("baseline_win_rate_below_research_threshold")
        if median_improvement <= self._minimum_median_relative_mse_improvement:
            reasons.append("median_mse_improvement_not_positive_enough")
        if median_sign_accuracy < self._minimum_median_sign_accuracy:
            reasons.append("median_sign_accuracy_below_research_threshold")
        if blocked_ratio > self._maximum_blocked_fold_ratio:
            reasons.append("too_many_blocked_folds")

        return {
            "horizonDays": self._safe_horizon(horizon),
            "evaluated": True,
            "passesResearchGate": not reasons,
            "foldCount": fold_count,
            "evaluatedFoldCount": evaluated_folds,
            "blockedFoldCount": blocked_folds,
            "blockedFoldRatio": blocked_ratio,
            "baselineWinRate": baseline_win_rate,
            "medianRelativeMseImprovement": median_improvement,
            "medianSignAccuracy": median_sign_accuracy,
            "reasons": reasons,
        }

    def _thresholds(self) -> dict[str, Any]:
        return {
            "minimumEvaluatedHorizons": self._minimum_evaluated_horizons,
            "minimumPassingHorizons": self._minimum_passing_horizons,
            "minimumEvaluatedFoldsPerHorizon": self._minimum_evaluated_folds_per_horizon,
            "minimumHorizonPassRatio": self._minimum_horizon_pass_ratio,
            "minimumFoldBaselineWinRate": self._minimum_fold_baseline_win_rate,
            "minimumMedianRelativeMseImprovement": self._minimum_median_relative_mse_improvement,
            "minimumMedianSignAccuracy": self._minimum_median_sign_accuracy,
            "maximumBlockedFoldRatio": self._maximum_blocked_fold_ratio,
        }

    def _safe_horizon(self, value: str) -> int | str:
        try:
            return int(value)
        except ValueError:
            return value

    def _non_negative_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed < 0:
            raise ValueError(f"{field} no puede ser negativo.")
        return parsed

    def _finite_float(self, value: object, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{field} debe ser finito.")
        return parsed

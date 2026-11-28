from __future__ import annotations

import math
from typing import Any


class RecommendationShadowHoldoutGateService:
    """Assess fresh independent holdouts without creating investment actions.

    This is deliberately a research promotion gate. Passing means that a frozen
    protocol has earned the right to enter *shadow action-threshold calibration*;
    it never means production approval or investment advice.
    """

    def __init__(
        self,
        *,
        minimum_evaluated_horizons: int = 3,
        minimum_passing_horizons: int = 2,
        minimum_horizon_pass_ratio: float = 2.0 / 3.0,
        minimum_holdout_rows_per_horizon: int = 20,
        minimum_relative_mse_improvement: float = 0.0,
        minimum_sign_accuracy: float = 0.5,
    ) -> None:
        if minimum_evaluated_horizons <= 0 or minimum_passing_horizons <= 0:
            raise ValueError("Los mínimos de horizontes deben ser positivos.")
        if minimum_passing_horizons > minimum_evaluated_horizons:
            raise ValueError("minimum_passing_horizons no puede superar minimum_evaluated_horizons.")
        if minimum_holdout_rows_per_horizon <= 0:
            raise ValueError("minimum_holdout_rows_per_horizon debe ser positivo.")
        for name, value in (
            ("minimum_horizon_pass_ratio", minimum_horizon_pass_ratio),
            ("minimum_sign_accuracy", minimum_sign_accuracy),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} debe estar entre 0 y 1.")
        if not math.isfinite(float(minimum_relative_mse_improvement)):
            raise ValueError("minimum_relative_mse_improvement debe ser finito.")

        self._minimum_evaluated_horizons = int(minimum_evaluated_horizons)
        self._minimum_passing_horizons = int(minimum_passing_horizons)
        self._minimum_horizon_pass_ratio = float(minimum_horizon_pass_ratio)
        self._minimum_holdout_rows_per_horizon = int(minimum_holdout_rows_per_horizon)
        self._minimum_relative_mse_improvement = float(minimum_relative_mse_improvement)
        self._minimum_sign_accuracy = float(minimum_sign_accuracy)

    def evaluate(self, *, holdouts: dict[int | str, dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(holdouts, dict) or not holdouts:
            raise ValueError("holdouts debe contener evidencia por horizonte.")

        checks: dict[str, dict[str, Any]] = {}
        fingerprints: set[str] = set()
        evaluated_count = 0
        passing_count = 0
        for raw_horizon, evidence in holdouts.items():
            horizon = self._positive_int(raw_horizon, "horizon")
            key = str(horizon)
            if key in checks:
                raise ValueError("No se permiten horizontes duplicados.")
            check = self._check_horizon(horizon, evidence)
            checks[key] = check
            fingerprint = check.get("modelFingerprint")
            if isinstance(fingerprint, str) and fingerprint:
                fingerprints.add(fingerprint)
            if check["evaluated"]:
                evaluated_count += 1
            if check["passesHoldoutGate"]:
                passing_count += 1

        pass_ratio = passing_count / evaluated_count if evaluated_count else 0.0
        reasons: list[str] = []
        if evaluated_count < self._minimum_evaluated_horizons:
            reasons.append("insufficient_evaluated_holdout_horizons")
        if passing_count < self._minimum_passing_horizons:
            reasons.append("insufficient_passing_holdout_horizons")
        if evaluated_count and pass_ratio < self._minimum_horizon_pass_ratio:
            reasons.append("insufficient_holdout_horizon_pass_ratio")

        eligible = not reasons
        return {
            "status": (
                "shadow_candidate_may_enter_action_threshold_calibration"
                if eligible
                else "shadow_candidate_fails_independent_holdout_gate"
            ),
            "evaluatedHorizonCount": evaluated_count,
            "passingHorizonCount": passing_count,
            "horizonPassRatio": pass_ratio,
            "actionThresholdCalibrationResearchEligible": eligible,
            "globalReasons": reasons,
            "horizons": checks,
            "modelFingerprintCount": len(fingerprints),
            "thresholds": self._thresholds(),
            "thresholdStatus": "provisional_research_only",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "passingMeaning": "eligible_only_for_shadow_action_threshold_calibration",
                "holdoutEvidence": "independent_and_consumed_once_used_for_promotion",
                "actions": "not_assigned",
                "thresholdsCanBeFitOnTheseHoldouts": False,
                "freshEvidenceRequiredAfterThresholdCalibration": True,
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
            },
        }

    def _check_horizon(self, horizon: int, evidence: object) -> dict[str, Any]:
        if not isinstance(evidence, dict):
            return self._not_evaluated(horizon, "holdout_missing_or_invalid")
        if evidence.get("productionEligible") is not False:
            raise ValueError(f"El holdout {horizon} violó productionEligible=False.")
        if evidence.get("advisoryStatus") != "no_advice":
            raise ValueError(f"El holdout {horizon} violó el contrato no_advice.")
        if evidence.get("status") != "shadow_independent_holdout_evaluated":
            return self._not_evaluated(horizon, str(evidence.get("status", "holdout_not_evaluated")))
        reported = self._positive_int(evidence.get("horizonDays"), "horizonDays")
        if reported != horizon:
            raise ValueError(f"El holdout {horizon} reporta un horizonte distinto.")

        rows = self._non_negative_int(evidence.get("holdoutRowCount"), "holdoutRowCount")
        improvement = self._finite_float(
            evidence.get("relativeMseImprovement"), "relativeMseImprovement"
        )
        metrics = evidence.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"El holdout {horizon} no contiene metrics válidas.")
        sign_accuracy = self._finite_float(metrics.get("signAccuracy"), "signAccuracy")
        if not 0.0 <= sign_accuracy <= 1.0:
            raise ValueError("signAccuracy debe estar entre 0 y 1.")
        beats_baseline = evidence.get("beatsZeroBaselineOnMse") is True

        reasons: list[str] = []
        if rows < self._minimum_holdout_rows_per_horizon:
            reasons.append("insufficient_independent_holdout_rows")
        if not beats_baseline:
            reasons.append("does_not_beat_zero_excess_baseline")
        if improvement <= self._minimum_relative_mse_improvement:
            reasons.append("relative_mse_improvement_not_positive_enough")
        if sign_accuracy < self._minimum_sign_accuracy:
            reasons.append("sign_accuracy_below_holdout_threshold")

        fingerprint = evidence.get("modelFingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            reasons.append("missing_model_fingerprint")

        return {
            "horizonDays": horizon,
            "evaluated": True,
            "passesHoldoutGate": not reasons,
            "holdoutRowCount": rows,
            "relativeMseImprovement": improvement,
            "signAccuracy": sign_accuracy,
            "beatsZeroBaselineOnMse": beats_baseline,
            "modelFingerprint": fingerprint,
            "reasons": reasons,
        }

    def _not_evaluated(self, horizon: int, reason: str) -> dict[str, Any]:
        return {
            "horizonDays": horizon,
            "evaluated": False,
            "passesHoldoutGate": False,
            "reasons": [reason],
        }

    def _thresholds(self) -> dict[str, Any]:
        return {
            "minimumEvaluatedHorizons": self._minimum_evaluated_horizons,
            "minimumPassingHorizons": self._minimum_passing_horizons,
            "minimumHorizonPassRatio": self._minimum_horizon_pass_ratio,
            "minimumHoldoutRowsPerHorizon": self._minimum_holdout_rows_per_horizon,
            "minimumRelativeMseImprovement": self._minimum_relative_mse_improvement,
            "minimumSignAccuracy": self._minimum_sign_accuracy,
        }

    def _positive_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return parsed

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

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)
from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)


class RecommendationShadowPostSelectionConfirmationService:
    """Evaluate a frozen candidate only on evidence unseen after model selection.

    Independent holdouts that were inspected while choosing among research cohorts
    become selection evidence. They cannot subsequently be reused as an untouched
    confirmation set. This service introduces a second temporal embargo:
    ``confirmation_start`` must be strictly after the model research cutoff and
    only feature snapshots strictly after that instant may enter confirmation.

    The frozen model is never refit, feature engineering is never relearned, and
    the result cannot assign actions or promote a model to production.
    """

    def __init__(
        self,
        *,
        dataset_service: RecommendationShadowCalibrationDatasetService | None = None,
        frozen_model_service: RecommendationShadowIndependentHoldoutService | None = None,
        minimum_confirmation_rows: int = 20,
    ) -> None:
        if minimum_confirmation_rows <= 0:
            raise ValueError("minimum_confirmation_rows debe ser positivo.")
        self._dataset_service = dataset_service or RecommendationShadowCalibrationDatasetService()
        self._frozen_model_service = frozen_model_service or RecommendationShadowIndependentHoldoutService(
            dataset_service=self._dataset_service
        )
        self._minimum_confirmation_rows = int(minimum_confirmation_rows)

    def evaluate(
        self,
        *,
        frozen_model: dict[str, Any],
        confirmation_start: datetime,
        as_of: datetime,
    ) -> dict[str, Any]:
        start = self._aware_utc(confirmation_start, "confirmation_start")
        cutoff = self._aware_utc(as_of, "as_of")
        model = self._frozen_model_service._validated_model(frozen_model)
        research_cutoff = self._parse_utc(model.get("researchCutoff"), "researchCutoff")

        if start <= research_cutoff:
            raise ValueError(
                "confirmation_start debe ser estrictamente posterior al researchCutoff."
            )
        if cutoff <= start:
            raise ValueError("as_of debe ser posterior a confirmation_start.")

        dataset = self._dataset_service.build(
            as_of=cutoff,
            horizon_days=int(model["horizonDays"]),
            require_benchmark=True,
        )
        rows: list[dict[str, Any]] = []
        excluded_before_confirmation = 0
        excluded_not_mature = 0
        for row in dataset.get("rows", []):
            feature_time = self._parse_utc(row.get("dataCutoffAt"), "dataCutoffAt")
            outcome_time = self._parse_utc(
                row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
            )
            if feature_time <= start:
                excluded_before_confirmation += 1
                continue
            if outcome_time > cutoff:
                excluded_not_mature += 1
                continue
            rows.append(row)

        common = {
            "modelFingerprint": model["fingerprint"],
            "researchCutoff": research_cutoff.isoformat(),
            "confirmationStart": start.isoformat(),
            "asOf": cutoff.isoformat(),
            "horizonDays": int(model["horizonDays"]),
            "excludedBeforeOrAtConfirmationStartCount": excluded_before_confirmation,
            "excludedNotMatureCount": excluded_not_mature,
        }
        if len(rows) < self._minimum_confirmation_rows:
            return {
                "status": "insufficient_post_selection_confirmation_data",
                **common,
                "confirmationRowCount": len(rows),
                "minimumConfirmationRows": self._minimum_confirmation_rows,
                "postSelectionConfirmationEvidenceReady": False,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": self._policy(),
            }

        predictions = [
            self._frozen_model_service._predict_row(row, model) for row in rows
        ]
        actual = self._frozen_model_service._targets(rows)
        metrics = self._frozen_model_service._metrics(actual, predictions)
        baseline = self._frozen_model_service._metrics(
            actual, [0.0 for _ in actual]
        )
        relative_mse_improvement = (
            (baseline["mse"] - metrics["mse"]) / baseline["mse"]
            if baseline["mse"] > 0
            else 0.0
        )
        if not math.isfinite(relative_mse_improvement):
            raise ValueError("La mejora relativa de confirmación no es finita.")

        return {
            "status": "shadow_post_selection_confirmation_evaluated",
            **common,
            "confirmationRowCount": len(rows),
            "minimumConfirmationRows": self._minimum_confirmation_rows,
            "metrics": metrics,
            "zeroExcessReturnBaseline": baseline,
            "relativeMseImprovement": relative_mse_improvement,
            "beatsZeroBaselineOnMse": metrics["mse"] < baseline["mse"],
            "postSelectionConfirmationEvidenceReady": True,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def _policy(self) -> dict[str, Any]:
        return {
            "independence": "features_strictly_after_post_selection_confirmation_start",
            "maturity": "outcome_evaluated_at_not_after_as_of",
            "modelParameters": "frozen_and_fingerprint_verified",
            "priorResearchEvidenceReusable": False,
            "priorHoldoutSelectionEvidenceReusable": False,
            "refit": False,
            "featureSelection": False,
            "thresholdCalibration": False,
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
        }

    def _parse_utc(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.repositories.recommendation_shadow_holdout_seal_repository import (
    RecommendationShadowHoldoutSealRepository,
)
from app.services.recommendation_shadow_holdout_pipeline_service import (
    RecommendationShadowHoldoutPipelineService,
)


class RecommendationShadowHoldoutSealService:
    """Seal the first sufficiently mature independent holdout for a cohort.

    Once a cohort has enough independent horizons to be judged, its first result
    is immutable. Every distinct cohort that reaches independent holdout is also
    registered as an experiment. Until a formal multiple-testing correction is
    implemented, more than one attempted cohort revokes downstream threshold-
    calibration eligibility even when an individual raw holdout gate passes.
    """

    def __init__(
        self,
        *,
        pipeline_service: RecommendationShadowHoldoutPipelineService | None = None,
        repository: RecommendationShadowHoldoutSealRepository | None = None,
    ) -> None:
        self._pipeline_service = pipeline_service or RecommendationShadowHoldoutPipelineService()
        self._repository = repository or RecommendationShadowHoldoutSealRepository()

    def evaluate_and_seal(
        self,
        *,
        as_of: datetime,
        horizons: Iterable[int] = RecommendationShadowHoldoutPipelineService.DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        pipeline = self._pipeline_service.evaluate_latest_cohort(
            as_of=cutoff,
            horizons=horizons,
        )
        self._assert_shadow(pipeline, "holdout_pipeline")
        if pipeline.get("status") != "shadow_holdout_pipeline_evaluated":
            return {
                **pipeline,
                "holdoutSealed": False,
                "sealReason": "no_evaluable_cohort",
            }

        gate_fingerprint = self._required_text(
            pipeline.get("researchGateFingerprint"), "researchGateFingerprint"
        )
        research_cutoff = self._required_text(
            pipeline.get("researchCutoff"), "researchCutoff"
        )

        self._repository.register_attempt(
            research_gate_fingerprint=gate_fingerprint,
            research_cutoff=research_cutoff,
            attempted_at=cutoff,
        )

        existing = self._repository.get(
            research_gate_fingerprint=gate_fingerprint,
            research_cutoff=research_cutoff,
        )
        if existing is not None:
            return self._sealed_response(existing, reused=True)

        holdout_gate = pipeline.get("holdoutGate")
        if not isinstance(holdout_gate, dict):
            raise ValueError("El pipeline holdout no contiene holdoutGate válida.")
        self._assert_shadow(holdout_gate, "holdout_gate")
        thresholds = holdout_gate.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("La holdout gate no contiene thresholds verificables.")
        minimum = self._positive_int(
            thresholds.get("minimumEvaluatedHorizons"),
            "minimumEvaluatedHorizons",
        )
        evaluated = self._non_negative_int(
            holdout_gate.get("evaluatedHorizonCount"),
            "evaluatedHorizonCount",
        )
        if evaluated < minimum:
            return {
                **pipeline,
                "holdoutSealed": False,
                "sealReason": "insufficient_mature_horizons_to_seal",
                "evaluatedHorizonCount": evaluated,
                "minimumEvaluatedHorizonsToSeal": minimum,
                "experimentMultiplicity": self._repository.multiplicity_summary(),
            }

        sealed = self._repository.seal(pipeline=pipeline, sealed_at=cutoff)
        return self._sealed_response(sealed, reused=False)

    def _sealed_response(self, record: dict[str, Any], *, reused: bool) -> dict[str, Any]:
        pipeline = record.get("pipeline")
        if not isinstance(pipeline, dict):
            raise ValueError("El registro sellado no contiene pipeline íntegro.")
        self._assert_shadow(pipeline, "sealed_pipeline")
        gate = pipeline.get("holdoutGate")
        if not isinstance(gate, dict):
            raise ValueError("El pipeline sellado no contiene holdoutGate.")
        self._assert_shadow(gate, "sealed_holdout_gate")

        multiplicity = self._repository.multiplicity_summary()
        raw_eligible = gate.get("actionThresholdCalibrationResearchEligible") is True
        multiplicity_controlled = multiplicity.get("multiplicityControlled") is True
        final_eligible = raw_eligible and multiplicity_controlled

        return {
            "status": "shadow_independent_holdout_sealed",
            "holdoutSealed": True,
            "reusedExistingSeal": reused,
            "sealId": int(record["id"]),
            "sealedAt": record["sealed_at"],
            "pipelineFingerprint": record["pipeline_fingerprint"],
            "researchGateFingerprint": record["research_gate_fingerprint"],
            "researchCutoff": record["research_cutoff"],
            "holdoutGate": gate,
            "rawHoldoutGateEligible": raw_eligible,
            "experimentMultiplicity": multiplicity,
            "actionThresholdCalibrationResearchEligible": final_eligible,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "firstSufficientHoldoutResultIsImmutable": True,
                "repeatUntilPass": False,
                "sameCohortRetestForPromotion": False,
                "distinctHoldoutCohortsTracked": True,
                "multipleExperimentSelectionBlocked": True,
                "uncorrectedMultiplicityMayPromote": False,
                "thresholdsCanBeFitOnThisHoldout": False,
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
            },
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

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

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_research_outcome_oos_cohort_repository import (
    RecommendationResearchOutcomeOosCohortRepository,
)
from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)
from app.services.recommendation_calibration_service import (
    RecommendationCalibrationService,
)
from app.services.recommendation_drift_service import RecommendationDriftService
from app.services.recommendation_evaluation_schedule_service import (
    RecommendationEvaluationScheduleService,
)
from app.services.recommendation_performance_service import (
    RecommendationPerformanceService,
)
from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)
from app.services.recommendation_shadow_live_longitudinal_service import (
    RecommendationShadowLiveLongitudinalService,
)


class RecommendationLearningStatusService:
    """Build one auditable status for ATHENA recommendation learning."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        shadow_longitudinal_service: RecommendationShadowLiveLongitudinalService
        | None = None,
        research_outcome_oos_cohort_repository: RecommendationResearchOutcomeOosCohortRepository
        | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        if shadow_longitudinal_service is not None:
            self._shadow_longitudinal_service = shadow_longitudinal_service
        else:
            candidate_repository = RecommendationShadowLiveCandidateRepository(
                self._database
            )
            snapshot_repository = RecommendationShadowRepository(self._database)
            evaluation_service = RecommendationShadowLiveCandidateEvaluationService(
                candidate_repository=candidate_repository,
                snapshot_repository=snapshot_repository,
            )
            self._shadow_longitudinal_service = (
                RecommendationShadowLiveLongitudinalService(
                    candidate_repository=candidate_repository,
                    evaluation_service=evaluation_service,
                )
            )
        self._research_outcome_oos_cohort_repository = (
            research_outcome_oos_cohort_repository
            or RecommendationResearchOutcomeOosCohortRepository(self._database)
        )

    def get_status(
        self,
        *,
        as_of: datetime,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> dict[str, Any]:
        performance = RecommendationPerformanceService(
            database=self._database
        ).get_report(
            model_version=model_version,
            horizon_days=horizon_days,
        )
        calibration = RecommendationCalibrationService(
            database=self._database
        ).get_report(
            model_version=model_version,
            horizon_days=horizon_days,
        )
        schedule = RecommendationEvaluationScheduleService(
            database=self._database
        ).get_report(as_of=as_of)

        drift: dict[str, Any] | None = None
        if model_version is not None and horizon_days is not None:
            drift = RecommendationDriftService(
                database=self._database
            ).get_report(
                model_version=model_version,
                horizon_days=horizon_days,
                as_of=as_of,
            ).to_api_dict()

        shadow_live_longitudinal = self._shadow_longitudinal_service.evaluate(
            as_of=as_of,
            horizons=(horizon_days,) if horizon_days is not None else (7, 30, 90, 180, 365),
        )
        self._assert_shadow_longitudinal_safe(shadow_live_longitudinal)

        research_outcome_oos = self._research_outcome_oos_status(as_of=as_of)
        self._assert_research_outcome_oos_safe(research_outcome_oos)

        return {
            "status": "learning_diagnostics_only",
            "asOf": schedule.as_of,
            "filters": {
                "modelVersion": model_version,
                "horizonDays": horizon_days,
            },
            "performance": performance.to_api_dict(),
            "calibration": calibration.to_api_dict(),
            "evaluationSchedule": schedule.to_api_dict(),
            "drift": drift,
            "shadowLiveLongitudinal": shadow_live_longitudinal,
            "researchOutcomeOos": research_outcome_oos,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _research_outcome_oos_status(self, *, as_of: datetime) -> dict[str, Any]:
        record = self._research_outcome_oos_cohort_repository.get_latest_at_or_before(
            as_of=as_of
        )
        if record is None:
            return {
                "status": "research_outcome_oos_evidence_pending",
                "cohortId": None,
                "cohortHash": None,
                "cohortAsOf": None,
                "observationCount": 0,
                "distinctResolvedIssuerCount": 0,
                "unresolvedIssuerObservationCount": 0,
                "horizonCount": 0,
                "horizons": {},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
                "recommendationCandidateReady": False,
                "productionLearningEligible": False,
                "policy": {
                    "source": "latest_tamper_verified_persisted_professional_research_outcome_cohort_at_or_before_as_of",
                    "availability": "no_eligible_persisted_cohort_at_cutoff",
                    "learningUse": "diagnostic_only_not_automatic_model_update",
                    "automaticModelMutation": False,
                    "automaticProductionPromotion": False,
                    "automaticTrading": False,
                },
            }

        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("La OOS cohort persistida carece de artifact válido.")
        horizons = artifact.get("horizons")
        if not isinstance(horizons, dict):
            raise ValueError("La OOS cohort persistida carece de horizontes válidos.")
        horizon_summary: dict[str, dict[str, Any]] = {}
        for key, value in sorted(horizons.items()):
            if not isinstance(value, dict):
                raise ValueError("La OOS cohort contiene un horizonte inválido.")
            horizon_summary[str(key)] = {
                "horizonSeconds": value.get("horizonSeconds"),
                "horizonDays": value.get("horizonDays"),
                "observationCount": value.get("observationCount"),
                "resolvedIssuerObservationCount": value.get(
                    "resolvedIssuerObservationCount"
                ),
                "unresolvedIssuerObservationCount": value.get(
                    "unresolvedIssuerObservationCount"
                ),
                "distinctResolvedIssuerCount": value.get(
                    "distinctResolvedIssuerCount"
                ),
                "maximumObservationsPerResolvedIssuer": value.get(
                    "maximumObservationsPerResolvedIssuer"
                ),
                "metrics": value.get("metrics"),
            }

        return {
            "status": "research_outcome_oos_evidence_available",
            "cohortId": artifact.get("cohortId"),
            "cohortHash": artifact.get("cohortHash"),
            "cohortAsOf": artifact.get("asOf"),
            "observationCount": artifact.get("observationCount"),
            "distinctResolvedIssuerCount": artifact.get(
                "distinctResolvedIssuerCount"
            ),
            "unresolvedIssuerObservationCount": artifact.get(
                "unresolvedIssuerObservationCount"
            ),
            "horizonCount": artifact.get("horizonCount"),
            "horizons": horizon_summary,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": {
                "source": "latest_tamper_verified_persisted_professional_research_outcome_cohort_at_or_before_as_of",
                "availability": "cohort_hash_reverified_before_diagnostic_read",
                "learningUse": "diagnostic_only_not_automatic_model_update",
                "issuerDiversity": "reported_not_treated_as_statistical_independence",
                "horizonPooling": "forbidden",
                "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _assert_research_outcome_oos_safe(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("El diagnóstico OOS profesional debe ser un objeto.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El diagnóstico OOS profesional debe mantener no_advice.")
        for key in (
            "productionEligible",
            "isWeightingReady",
            "recommendationCandidateReady",
            "productionLearningEligible",
        ):
            if payload.get(key) is not False:
                raise ValueError(f"El diagnóstico OOS profesional intentó activar {key}.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El diagnóstico OOS profesional carece de policy.")
        if policy.get("learningUse") != "diagnostic_only_not_automatic_model_update":
            raise ValueError("El diagnóstico OOS intentó habilitar aprendizaje automático.")
        if policy.get("automaticModelMutation") is not False:
            raise ValueError("El diagnóstico OOS no puede mutar modelos automáticamente.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El diagnóstico OOS no puede promover producción.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El diagnóstico OOS no puede ejecutar operaciones.")

    def _assert_shadow_longitudinal_safe(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("El estado longitudinal shadow debe ser un objeto.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El estado longitudinal shadow debe mantener no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(
                "El estado longitudinal shadow no puede habilitar producción."
            )
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(
                "El estado longitudinal shadow no puede habilitar recomendaciones."
            )
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El estado longitudinal shadow carece de política segura.")
        if policy.get("automaticModelMutation") is not False:
            raise ValueError("El aprendizaje shadow no puede mutar modelos automáticamente.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El aprendizaje shadow no puede promocionar producción.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El aprendizaje shadow no puede ejecutar operaciones.")

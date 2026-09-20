from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from app.repositories.longitudinal_oos_policy_repository import (
    LongitudinalOosPolicyRepository,
)
from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)
from app.services.recommendation_research_forecast_error_oos_service import (
    RecommendationResearchForecastErrorOosService,
)


class GovernedForecastErrorOosService:
    """Compose OOS measurement with durable human-governed sufficiency policy.

    Measurement remains descriptive and policy-independent. The policy repository
    is read point-in-time at the same ``as_of`` cutoff; no policy is created,
    approved, promoted, or mutated by this service.
    """

    def __init__(
        self,
        *,
        measurement_service: RecommendationResearchForecastErrorOosService | None = None,
        policy_service: LongitudinalOosSufficiencyPolicyService | None = None,
        policy_repository: LongitudinalOosPolicyRepository | None = None,
    ) -> None:
        self._measurement = measurement_service or RecommendationResearchForecastErrorOosService()
        self._policy = policy_service or LongitudinalOosSufficiencyPolicyService()
        self._repository = policy_repository or LongitudinalOosPolicyRepository()

    def evaluate(
        self,
        *,
        as_of: datetime,
        cohort_record: dict[str, Any] | None,
        error_records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        measurement = self._measurement.evaluate(
            as_of=as_of,
            cohort_record=cohort_record,
            error_records=error_records,
        )
        self._validate_measurement_contract(measurement)
        policy_record = self._repository.get_latest_policy(as_of=as_of)
        approval_record = None
        if policy_record is not None:
            artifact = policy_record.get("artifact")
            if not isinstance(artifact, dict):
                raise RuntimeError("La política longitudinal persistida perdió artifact.")
            fingerprint = artifact.get("policyFingerprint")
            if not isinstance(fingerprint, str):
                raise RuntimeError("La política longitudinal persistida perdió policyFingerprint.")
            approval_record = self._repository.get_latest_approval(
                policy_fingerprint=fingerprint,
                as_of=as_of,
            )

        sufficiency = self._policy.evaluate(
            as_of=as_of,
            measurement=measurement,
            policy_record=policy_record,
            approval_record=approval_record,
        )
        result = dict(measurement)
        result["longitudinalSufficiency"] = sufficiency
        result["productionLearningEligible"] = False
        result["productionEligible"] = False
        result["recommendationCandidateReady"] = False
        result["isWeightingReady"] = False
        policy = result.get("policy")
        if isinstance(policy, dict):
            policy = dict(policy)
            policy["longitudinalSufficiency"] = "durable_precommitted_human_approved_policy_required"
            policy["automaticProductionPromotion"] = False
            policy["automaticModelMutation"] = False
            policy["automaticTrading"] = False
            result["policy"] = policy
        return result

    @classmethod
    def _validate_measurement_contract(cls, measurement: dict[str, Any]) -> None:
        if not isinstance(measurement, dict):
            raise RuntimeError("La medición OOS gobernada no es estructurada.")
        span = measurement.get("evaluationSpanDays")
        if isinstance(span, bool) or not isinstance(span, (int, float)) or not math.isfinite(float(span)) or float(span) < 0:
            raise RuntimeError("La medición OOS contiene evaluationSpanDays inválido.")
        counts: dict[str, int] = {}
        for field in (
            "distinctEvaluationPeriodCount",
            "eligibleOutcomeCount",
            "forecastErrorCount",
            "distinctResolvedIssuerCount",
        ):
            counts[field] = cls._require_nonnegative_int(measurement.get(field), field)
        if counts["forecastErrorCount"] > counts["eligibleOutcomeCount"]:
            raise RuntimeError("La medición OOS contiene más forecast errors que outcomes elegibles.")
        horizons = measurement.get("horizons")
        if not isinstance(horizons, dict):
            raise RuntimeError("La medición OOS gobernada carece de horizons estructurados.")
        horizon_error_total = 0
        for horizon, payload in horizons.items():
            if not isinstance(horizon, str) or not horizon.strip() or not isinstance(payload, dict):
                raise RuntimeError("La medición OOS contiene un horizonte inválido.")
            horizon_error_total += cls._require_nonnegative_int(
                payload.get("forecastErrorCount"),
                f"horizons.{horizon}.forecastErrorCount",
            )
        if horizon_error_total != counts["forecastErrorCount"]:
            raise RuntimeError("La medición OOS no reconcilia forecastErrorCount con sus horizontes.")

    @staticmethod
    def _require_nonnegative_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"La medición OOS contiene {field} inválido.")
        return value

from __future__ import annotations

from datetime import datetime
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

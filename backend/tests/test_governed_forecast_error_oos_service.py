from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.longitudinal_oos_policy_repository import (
    LongitudinalOosPolicyRepository,
)
from app.services.governed_forecast_error_oos_service import (
    GovernedForecastErrorOosService,
)


class _MeasurementService:
    def __init__(self, measurement: dict) -> None:
        self.measurement = measurement

    def evaluate(self, *, as_of, cohort_record, error_records):
        return dict(self.measurement)


def _measurement() -> dict:
    return {
        "module": "research_forecast_error_oos_diagnostic",
        "status": "forecast_error_oos_evidence_available",
        "eligibleOutcomeCount": 120,
        "forecastErrorCount": 120,
        "missingForecastErrorCount": 0,
        "measurementCoverage": 1.0,
        "distinctResolvedIssuerCount": 24,
        "distinctEvaluationPeriodCount": 8,
        "evaluationSpanDays": 210.0,
        "horizonCount": 2,
        "horizons": {
            "86400": {"eligibleOutcomeCount": 60, "forecastErrorCount": 60},
            "604800": {"eligibleOutcomeCount": 60, "forecastErrorCount": 60},
        },
        "longitudinalSufficiency": {"status": "policy_not_precommitted"},
        "productionLearningEligible": False,
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
        },
    }


def _criteria() -> dict:
    return {
        "minimumEvaluationSpanDays": 180,
        "minimumDistinctEvaluationPeriods": 6,
        "minimumEligibleOutcomes": 100,
        "minimumDistinctResolvedIssuers": 20,
        "requiredHorizonSeconds": [86400, 604800],
        "dependencyHandling": "issuer_clustered_period_aware_review",
    }


def test_governed_oos_reads_persisted_policy_and_human_approval(tmp_path) -> None:
    repository = LongitudinalOosPolicyRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=_criteria(),
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )
    repository.approve_policy(
        policy_fingerprint=policy["artifact"]["policyFingerprint"],
        approved_by="human-reviewer",
        evidence_ref="signed-approval",
        human_review_confirmed=True,
    )
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(_measurement()),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=datetime.now(timezone.utc), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "precommitted_policy_satisfied"
    assert result["longitudinalSufficiency"]["policyApproved"] is True
    assert result["longitudinalSufficiency"]["acceptanceEvidenceVerified"] is True
    assert result["longitudinalSufficiency"]["productionSufficiencyClaimed"] is False
    assert result["productionLearningEligible"] is False
    assert result["productionEligible"] is False
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["policy"]["automaticModelMutation"] is False
    assert result["policy"]["automaticTrading"] is False


def test_governed_oos_fails_closed_without_policy(tmp_path) -> None:
    repository = LongitudinalOosPolicyRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(_measurement()),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=datetime.now(timezone.utc), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "policy_not_precommitted"
    assert result["longitudinalSufficiency"]["policyApproved"] is False
    assert result["productionLearningEligible"] is False


def test_governed_oos_uses_same_point_in_time_cutoff_for_policy_and_approval(tmp_path) -> None:
    repository = LongitudinalOosPolicyRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )
    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=_criteria(),
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )
    repository.approve_policy(
        policy_fingerprint=policy["artifact"]["policyFingerprint"],
        approved_by="human-reviewer",
        evidence_ref="signed-approval",
        human_review_confirmed=True,
    )
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(_measurement()),
        policy_repository=repository,
    )

    result = service.evaluate(as_of=before, cohort_record=None, error_records=[])

    assert result["longitudinalSufficiency"]["status"] == "policy_not_precommitted"
    assert result["longitudinalSufficiency"]["acceptanceEvidenceVerified"] is False


def test_policy_can_be_approved_but_real_measurement_can_still_fail(tmp_path) -> None:
    repository = LongitudinalOosPolicyRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=_criteria(),
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )
    repository.approve_policy(
        policy_fingerprint=policy["artifact"]["policyFingerprint"],
        approved_by="human-reviewer",
        evidence_ref="signed-approval",
        human_review_confirmed=True,
    )
    measurement = _measurement()
    measurement["evaluationSpanDays"] = 30.0
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(measurement),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=datetime.now(timezone.utc), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "precommitted_policy_not_satisfied"
    assert result["longitudinalSufficiency"]["policyApproved"] is True
    assert result["longitudinalSufficiency"]["acceptanceEvidenceVerified"] is False
    assert result["productionLearningEligible"] is False

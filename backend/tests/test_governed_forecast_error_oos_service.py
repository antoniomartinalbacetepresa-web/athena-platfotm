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


def _measurement(*, first_period_end: datetime | None = None) -> dict:
    first = first_period_end or (datetime.now(timezone.utc) + timedelta(days=1))
    last = first + timedelta(days=210)
    return {
        "module": "research_forecast_error_oos_diagnostic",
        "status": "forecast_error_oos_evidence_available",
        "eligibleOutcomeCount": 120,
        "forecastErrorCount": 120,
        "missingForecastErrorCount": 0,
        "measurementCoverage": 1.0,
        "distinctResolvedIssuerCount": 24,
        "distinctEvaluationPeriodCount": 8,
        "firstEvaluationPeriodStart": (first - timedelta(hours=1)).isoformat(),
        "firstEvaluationPeriodEnd": first.isoformat(),
        "lastEvaluationPeriodEnd": last.isoformat(),
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
    first_period = datetime.now(timezone.utc) + timedelta(days=1)
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(
            _measurement(first_period_end=first_period)
        ),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=first_period + timedelta(days=211), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "precommitted_policy_satisfied"
    assert result["longitudinalSufficiency"]["policyApproved"] is True
    assert result["longitudinalSufficiency"]["temporalPrecommitmentVerified"] is True
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
    first_period = datetime.now(timezone.utc) + timedelta(days=1)
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(
            _measurement(first_period_end=first_period)
        ),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=first_period + timedelta(days=211), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "policy_not_precommitted"
    assert result["longitudinalSufficiency"]["policyApproved"] is False
    assert result["longitudinalSufficiency"]["temporalPrecommitmentVerified"] is False
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
    first_period = datetime.now(timezone.utc) + timedelta(days=1)
    measurement = _measurement(first_period_end=first_period)
    measurement["evaluationSpanDays"] = 30.0
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(measurement),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=first_period + timedelta(days=211), cohort_record=None, error_records=[]
    )

    assert result["longitudinalSufficiency"]["status"] == "precommitted_policy_not_satisfied"
    assert result["longitudinalSufficiency"]["policyApproved"] is True
    assert result["longitudinalSufficiency"]["temporalPrecommitmentVerified"] is True
    assert result["longitudinalSufficiency"]["acceptanceEvidenceVerified"] is False
    assert result["productionLearningEligible"] is False


def test_governed_oos_rejects_retroactive_approval_of_historical_evidence(tmp_path) -> None:
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
    first_period = datetime.now(timezone.utc) - timedelta(days=211)
    service = GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(
            _measurement(first_period_end=first_period)
        ),
        policy_repository=repository,
    )

    result = service.evaluate(
        as_of=datetime.now(timezone.utc) + timedelta(days=1),
        cohort_record=None,
        error_records=[],
    )

    sufficiency = result["longitudinalSufficiency"]
    assert sufficiency["status"] == "precommitted_policy_not_satisfied"
    assert sufficiency["policyApproved"] is True
    assert sufficiency["temporalPrecommitmentVerified"] is False
    assert sufficiency["acceptanceEvidenceVerified"] is False
    assert sufficiency["criteriaCheckCount"] == 7
    assert sufficiency["satisfiedCriteriaCount"] == 6
    assert result["productionLearningEligible"] is False


def test_external_timesfm_challenger_is_pit_bound_and_has_no_automatic_authority(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)

    result = service.bind_external_challenger(
        provider="google",
        model_name="timesfm",
        model_version="research-pinned-version",
        model_config={"contextLength": 512, "quantiles": [0.1, 0.5, 0.9]},
        forecast_origin=origin,
        input_observed_through=origin - timedelta(hours=2),
        input_retrieved_at=origin - timedelta(hours=1),
        horizon_seconds=86400,
        forecast_value=101.25,
        baseline_name="last_value",
        baseline_value=100.0,
        source_provenance=[{
            "source": "market_history",
            "observedAt": (origin - timedelta(hours=2)).isoformat(),
            "retrievedAt": (origin - timedelta(hours=1)).isoformat(),
        }],
    )

    assert result["provider"] == "google"
    assert result["modelName"] == "timesfm"
    assert result["evaluationMode"] == "prospective_oos_paired_with_baseline"
    assert result["challengerOnly"] is True
    assert result["productionLearningEligible"] is False
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["isWeightingReady"] is False
    assert result["automaticModelPromotion"] is False
    assert result["automaticWeighting"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["authority"] == "research_diagnostic_only"


def test_external_challenger_rejects_lookahead_input(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)

    import pytest
    with pytest.raises(ValueError, match="PIT ordering"):
        service.bind_external_challenger(
            provider="google",
            model_name="timesfm",
            model_version="research-pinned-version",
            model_config={"contextLength": 512},
            forecast_origin=origin,
            input_observed_through=origin + timedelta(seconds=1),
            input_retrieved_at=origin - timedelta(minutes=1),
            horizon_seconds=86400,
            forecast_value=101.25,
            baseline_name="last_value",
            baseline_value=100.0,
            source_provenance=[{
                "source": "market_history",
                "observedAt": (origin - timedelta(hours=2)).isoformat(),
                "retrievedAt": (origin - timedelta(hours=1)).isoformat(),
            }],
        )


def test_external_challenger_rejects_provenance_retrieved_after_forecast_origin(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)

    import pytest
    with pytest.raises(ValueError, match="provenance violates"):
        service.bind_external_challenger(
            provider="google",
            model_name="timesfm",
            model_version="research-pinned-version",
            model_config={"contextLength": 512},
            forecast_origin=origin,
            input_observed_through=origin - timedelta(hours=2),
            input_retrieved_at=origin - timedelta(hours=1),
            horizon_seconds=86400,
            forecast_value=101.25,
            baseline_name="last_value",
            baseline_value=100.0,
            source_provenance=[{
                "source": "market_history",
                "observedAt": (origin - timedelta(hours=2)).isoformat(),
                "retrievedAt": (origin + timedelta(seconds=1)).isoformat(),
            }],
        )

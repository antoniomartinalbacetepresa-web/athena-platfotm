from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    assert sufficiency["criteriaCheckCount"] == 9  # Includes span and evidence-count coherence.
    assert sufficiency["satisfiedCriteriaCount"] == sufficiency["criteriaCheckCount"] - 1
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


def _external_challenger(service: GovernedForecastErrorOosService, origin: datetime) -> dict:
    return service.bind_external_challenger(
        provider="google",
        model_name="timesfm",
        model_version="research-pinned-version",
        model_config={"contextLength": 512},
        forecast_origin=origin,
        input_observed_through=origin - timedelta(hours=2),
        input_retrieved_at=origin - timedelta(hours=1),
        horizon_seconds=86400,
        forecast_value=105.0,
        baseline_name="last_value",
        baseline_value=100.0,
        source_provenance=[{
            "source": "market_history",
            "observedAt": (origin - timedelta(hours=2)).isoformat(),
            "retrievedAt": (origin - timedelta(hours=1)).isoformat(),
        }],
    )


def test_external_challenger_realized_error_is_paired_with_same_mature_outcome(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1, minutes=5)

    result = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=10),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=2),
    )

    assert result["absoluteError"] == 1.0
    assert result["baselineAbsoluteError"] == 4.0
    assert result["absoluteErrorDeltaVsBaseline"] == -3.0
    assert result["singleObservationSkillClaimed"] is False
    assert result["longitudinalGateRequired"] is True
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["automaticModelPromotion"] is False
    assert result["automaticWeighting"] is False
    assert result["automaticTrading"] is False


def test_external_challenger_realized_error_rejects_unmatured_outcome(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(hours=23)

    with pytest.raises(ValueError, match="not mature"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=origin + timedelta(days=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_external_challenger_realized_error_rejects_outcome_retrieved_after_as_of(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    cutoff = observed + timedelta(minutes=1)

    with pytest.raises(ValueError, match="outcome PIT ordering"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=cutoff,
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=cutoff + timedelta(seconds=1),
        )


def test_external_challenger_realized_error_rejects_authority_escalation(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["automaticWeighting"] = True
    observed = origin + timedelta(days=1)

    with pytest.raises(ValueError, match="forbidden authority"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_external_challenger_realized_error_preserves_revalidated_pit_metadata(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)

    result = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )

    assert result["modelConfig"] == {"contextLength": 512}
    assert result["inputObservedThrough"] == (origin - timedelta(hours=2)).isoformat()
    assert result["inputRetrievedAt"] == (origin - timedelta(hours=1)).isoformat()
    assert result["sourceProvenance"] == challenger["sourceProvenance"]


def test_external_challenger_realized_error_rejects_corrupted_input_pit_after_binding(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["inputRetrievedAt"] = (origin + timedelta(seconds=1)).isoformat()
    observed = origin + timedelta(days=1)

    with pytest.raises(ValueError, match="input PIT ordering was corrupted"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_external_challenger_realized_error_rejects_corrupted_provenance_after_binding(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["sourceProvenance"][0]["retrievedAt"] = (origin + timedelta(seconds=1)).isoformat()
    observed = origin + timedelta(days=1)

    with pytest.raises(ValueError, match="provenance PIT cutoff was corrupted"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_external_challenger_realized_error_rejects_missing_model_config_after_binding(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["modelConfig"] = {}
    observed = origin + timedelta(days=1)

    with pytest.raises(ValueError, match="modelConfig"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_external_challenger_longitudinal_diagnostic_reconciles_paired_errors(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    first_observed = origin + timedelta(days=1)
    first = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=first_observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=first_observed,
        outcome_retrieved_at=first_observed + timedelta(minutes=1),
    )
    second_origin = origin + timedelta(days=1)
    second_challenger = _external_challenger(service, second_origin)
    second_challenger["forecastValue"] = 98.0
    second_challenger["baselineValue"] = 100.0
    second_observed = second_origin + timedelta(days=1)
    second = service.measure_external_challenger_outcome(
        challenger=second_challenger,
        as_of=second_observed + timedelta(minutes=2),
        outcome_value=100.0,
        outcome_observed_at=second_observed,
        outcome_retrieved_at=second_observed + timedelta(minutes=1),
    )

    result = service.summarize_external_challenger_outcomes(
        error_records=[first, second]
    )

    assert result["observationCount"] == 2
    assert result["distinctForecastOriginCount"] == 2
    assert result["meanAbsoluteError"] == 1.5
    assert result["baselineMeanAbsoluteError"] == 2.0
    assert result["meanAbsoluteErrorDeltaVsBaseline"] == -0.5
    assert result["wins"] == 1
    assert result["ties"] == 0
    assert result["losses"] == 1
    assert result["winRate"] == 0.5
    assert result["skillClaimed"] is False
    assert result["calibrationClaimed"] is False
    assert result["productionEligible"] is False
    assert result["automaticModelPromotion"] is False
    assert result["automaticWeighting"] is False
    assert result["automaticTrading"] is False


def test_external_challenger_longitudinal_diagnostic_rejects_mixed_horizons(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    first = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    second = dict(first)
    second["forecastOrigin"] = (origin + timedelta(hours=1)).isoformat()
    second["horizonSeconds"] = 172800

    with pytest.raises(ValueError, match="share provider/model/version/horizon/baseline"):
        service.summarize_external_challenger_outcomes(error_records=[first, second])


def test_external_challenger_longitudinal_diagnostic_rejects_tampered_metric(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    error["absoluteError"] = 999.0

    with pytest.raises(ValueError, match="metric reconciliation"):
        service.summarize_external_challenger_outcomes(error_records=[error])


def test_external_challenger_longitudinal_diagnostic_rejects_authority_escalation(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    error["automaticWeighting"] = True

    with pytest.raises(ValueError, match="forbidden authority: automaticWeighting"):
        service.summarize_external_challenger_outcomes(error_records=[error])


def test_external_challenger_longitudinal_diagnostic_rejects_mixed_model_config(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    first = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    second = dict(first)
    second["forecastOrigin"] = (origin + timedelta(hours=1)).isoformat()
    second["modelConfig"] = {"contextLength": 256}

    with pytest.raises(ValueError, match="same modelConfig"):
        service.summarize_external_challenger_outcomes(error_records=[first, second])


def test_external_challenger_longitudinal_diagnostic_requires_human_gate(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    error["longitudinalGateRequired"] = False

    with pytest.raises(ValueError, match="longitudinal human gate"):
        service.summarize_external_challenger_outcomes(error_records=[error])


def test_external_challenger_longitudinal_diagnostic_rejects_duplicate_forecast_origin(tmp_path) -> None:
    import pytest

    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="distinct forecast origins"):
        service.summarize_external_challenger_outcomes(
            error_records=[error, dict(error)]
        )

@pytest.mark.parametrize(
    "tamper,expected",
    [
        ("input_retrieval", "input PIT ordering"),
        ("source_retrieval", "source provenance PIT ordering"),
        ("maturity", "maturity does not match"),
        ("unmatured", "precedes forecast maturity"),
        ("late_outcome", "outcome PIT ordering"),
        ("retroactive_as_of", "outcome PIT ordering"),
    ],
)
def test_challenger_longitudinal_summary_revalidates_pit_after_measurement(
    tmp_path, tamper: str, expected: str
) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=challenger,
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    if tamper == "input_retrieval":
        error["inputRetrievedAt"] = (origin + timedelta(seconds=1)).isoformat()
    elif tamper == "source_retrieval":
        error["sourceProvenance"][0]["retrievedAt"] = (
            origin + timedelta(seconds=1)
        ).isoformat()
    elif tamper == "maturity":
        error["maturityAt"] = (origin + timedelta(days=2)).isoformat()
    elif tamper == "unmatured":
        error["outcomeObservedAt"] = (origin + timedelta(hours=23)).isoformat()
    elif tamper == "late_outcome":
        error["outcomeRetrievedAt"] = (observed + timedelta(minutes=3)).isoformat()
    else:
        error["asOf"] = (observed - timedelta(minutes=1)).isoformat()

    with pytest.raises(ValueError, match=expected):
        service.summarize_external_challenger_outcomes(error_records=[error])


@pytest.mark.parametrize(
    "forecast,baseline,actual",
    [
        (1e308, 0.0, -1e308),  # finite inputs, infinite signed error
        (1e155, 0.0, 0.0),  # finite signed error, infinite square
        (0.0, 1e155, 0.0),  # baseline square also must remain finite
    ],
)
def test_challenger_rejects_overflowing_derived_errors(
    tmp_path, forecast: float, baseline: float, actual: float
) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["forecastValue"] = forecast
    challenger["baselineValue"] = baseline
    observed = origin + timedelta(days=1)
    with pytest.raises(ValueError, match="derived errors must be finite"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=actual,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )


def test_challenger_summary_rejects_recomputed_overflow_after_tampering(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    observed = origin + timedelta(days=1)
    error = service.measure_external_challenger_outcome(
        challenger=_external_challenger(service, origin),
        as_of=observed + timedelta(minutes=2),
        outcome_value=104.0,
        outcome_observed_at=observed,
        outcome_retrieved_at=observed + timedelta(minutes=1),
    )
    error["forecastValue"] = 1e155
    error["outcomeValue"] = 0.0
    with pytest.raises(ValueError, match="derived metrics must be finite"):
        service.summarize_external_challenger_outcomes(error_records=[error])


def test_challenger_longitudinal_rms_uses_finite_mean_before_square_root(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    errors = []
    for day in (0, 1):
        origin = datetime(2026, 9, 20 + day, 18, 0, tzinfo=timezone.utc)
        challenger = _external_challenger(service, origin)
        challenger["forecastValue"] = 1e154
        challenger["baselineValue"] = 0.0
        observed = origin + timedelta(days=1)
        errors.append(service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=0.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        ))
    summary = service.summarize_external_challenger_outcomes(error_records=errors)
    assert summary["observationCount"] == 2
    assert summary["meanAbsoluteError"] == 1e154
    assert summary["rootMeanSquaredError"] == 1e154
    assert summary["baselineRootMeanSquaredError"] == 0.0
    assert summary["skillClaimed"] is False


def test_challenger_rejects_unrepresentable_numeric_input(tmp_path) -> None:
    service = GovernedForecastErrorOosService(
        policy_repository=LongitudinalOosPolicyRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )
    origin = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    challenger = _external_challenger(service, origin)
    challenger["forecastValue"] = 10 ** 1000
    observed = origin + timedelta(days=1)
    with pytest.raises(ValueError, match="forecastValue must be finite"):
        service.measure_external_challenger_outcome(
            challenger=challenger,
            as_of=observed + timedelta(minutes=2),
            outcome_value=104.0,
            outcome_observed_at=observed,
            outcome_retrieved_at=observed + timedelta(minutes=1),
        )

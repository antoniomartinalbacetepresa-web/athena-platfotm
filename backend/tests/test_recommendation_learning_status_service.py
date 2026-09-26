from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


OUTCOME_HASH = "1" * 64
CYCLE_HASH = "2" * 64
ERROR_HASH = "3" * 64
SPECIFICATION_HASH = "4" * 64
PERIOD_START = "2026-08-01T12:00:00+00:00"
PERIOD_END = "2026-08-31T12:00:00+00:00"
HORIZON_SECONDS = 30 * 86400


class FakeShadowLongitudinalService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class FakeOosCohortRepository:
    def __init__(self, record=None):
        self.record = record
        self.calls = []

    def get_latest_at_or_before(self, *, as_of):
        self.calls.append(as_of)
        return self.record


class FakeForecastErrorRepository:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.calls = []

    def get_for_outcomes_at_or_before(self, *, outcome_hashes, as_of):
        self.calls.append({"outcome_hashes": list(outcome_hashes), "as_of": as_of})
        return list(self.records)


def _safe_shadow_payload():
    return {
        "status": "shadow_live_longitudinal_evidence_pending",
        "persistedCandidateCount": 0,
        "eligibleCandidateCount": 0,
        "evaluatedCandidateCount": 0,
        "evaluatedObservationCount": 0,
        "horizons": {},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "policy": {
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def _safe_oos_row():
    return {
        "outcomeHash": OUTCOME_HASH,
        "cycleHash": CYCLE_HASH,
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "periodStart": PERIOD_START,
        "periodEnd": PERIOD_END,
        "horizonSeconds": HORIZON_SECONDS,
        "totalReturn": 0.08,
        "issuerIdentity": {
            "status": "resolved",
            "issuerId": "issuer-apple",
            "availableAt": "2026-08-30T12:00:00+00:00",
            "source": "athena-identity",
            "sourceRef": "urn:issuer:apple",
            "resolutionMethod": "canonical_security_master",
        },
    }


def _safe_oos_record():
    return {
        "cohort_hash": "a" * 64,
        "artifact": {
            "module": "research_outcome_oos_cohort",
            "cohortId": "cohort-1",
            "cohortHash": "a" * 64,
            "asOf": "2026-08-31T12:00:00+00:00",
            "observationCount": 1,
            "distinctResolvedIssuerCount": 1,
            "unresolvedIssuerObservationCount": 0,
            "horizonCount": 1,
            "horizons": {
                str(HORIZON_SECONDS): {
                    "horizonSeconds": HORIZON_SECONDS,
                    "horizonDays": 30,
                    "observationCount": 1,
                    "resolvedIssuerObservationCount": 1,
                    "unresolvedIssuerObservationCount": 0,
                    "distinctResolvedIssuerCount": 1,
                    "maximumObservationsPerResolvedIssuer": 1,
                    "metrics": {
                        "meanTotalReturn": 0.08,
                        "meanResidualReturn": 0.01,
                    },
                }
            },
            "rows": [_safe_oos_row()],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "productionLearningEligible": False,
        },
    }


def _safe_forecast_error_record():
    signed = 0.08 - 0.10
    return {
        "error_hash": ERROR_HASH,
        "created_at": "2026-08-31T12:30:00+00:00",
        "artifact": {
            "module": "research_forecast_error",
            "errorHash": ERROR_HASH,
            "specificationHash": SPECIFICATION_HASH,
            "outcomeHash": OUTCOME_HASH,
            "cycleHash": CYCLE_HASH,
            "instrumentId": "instrument-aapl",
            "symbol": "AAPL",
            "periodStart": PERIOD_START,
            "periodEnd": PERIOD_END,
            "horizonSeconds": HORIZON_SECONDS,
            "expectedValue": 0.10,
            "realizedValue": 0.08,
            "signedError": signed,
            "absoluteError": abs(signed),
            "squaredError": signed * signed,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "recommendationCandidateReady": False,
            "productionLearningEligible": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "skillClaim": "forbidden_single_observation_is_not_evidence_of_skill",
            },
        },
    }


def _service(*, cohort=None, errors=None, shadow=None):
    return RecommendationLearningStatusService(
        shadow_longitudinal_service=shadow or FakeShadowLongitudinalService(_safe_shadow_payload()),
        research_outcome_oos_cohort_repository=FakeOosCohortRepository(cohort),
        research_forecast_error_repository=FakeForecastErrorRepository(errors),
    )


def test_learning_status_is_safe_on_empty_history(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    status = RecommendationLearningStatusService(database=database).get_status(
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert status["status"] == "learning_diagnostics_only"
    assert status["performance"]["sampleCount"] == 0
    assert status["calibration"]["autoApply"] is False
    assert status["evaluationSchedule"]["dueCount"] == 0
    assert status["drift"] is None
    assert status["shadowLiveLongitudinal"]["persistedCandidateCount"] == 0
    assert status["shadowLiveLongitudinal"]["evaluatedObservationCount"] == 0
    assert status["researchOutcomeOos"]["status"] == "research_outcome_oos_evidence_pending"
    assert status["researchForecastErrorOos"]["status"] == "forecast_error_oos_evidence_pending"
    assert status["researchForecastErrorOos"]["productionLearningEligible"] is False
    assert status["advisoryStatus"] == "no_advice"
    assert status["productionEligible"] is False
    assert status["isWeightingReady"] is False
    assert status["automaticModelMutation"] is False
    assert status["automaticProductionPromotion"] is False
    assert status["automaticTrading"] is False


def test_learning_status_includes_drift_only_with_complete_filter(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    service = RecommendationLearningStatusService(database=database)
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    without_horizon = service.get_status(as_of=as_of, model_version="v1")
    with_filter = service.get_status(
        as_of=as_of,
        model_version="v1",
        horizon_days=30,
    )

    assert without_horizon["drift"] is None
    assert with_filter["drift"] is not None
    assert with_filter["drift"]["status"] == "insufficient_sample"
    assert with_filter["filters"] == {"modelVersion": "v1", "horizonDays": 30}
    assert with_filter["shadowLiveLongitudinal"]["requestedHorizons"] == [30]


def test_learning_status_passes_same_cutoff_to_shadow_cohort_and_error_reads() -> None:
    shadow = FakeShadowLongitudinalService(_safe_shadow_payload())
    cohort_repo = FakeOosCohortRepository(_safe_oos_record())
    error_repo = FakeForecastErrorRepository([])
    as_of = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=shadow,
        research_outcome_oos_cohort_repository=cohort_repo,
        research_forecast_error_repository=error_repo,
    )

    status = service.get_status(as_of=as_of, horizon_days=90)

    assert shadow.calls == [{"as_of": as_of, "horizons": (90,)}]
    assert cohort_repo.calls == [as_of]
    assert error_repo.calls == [{"outcome_hashes": [OUTCOME_HASH], "as_of": as_of}]
    assert status["researchForecastErrorOos"]["forecastErrorCount"] == 0
    assert status["researchForecastErrorOos"]["eligibleOutcomeCount"] == 1


def test_learning_status_surfaces_verified_oos_and_precommitted_forecast_error_metrics() -> None:
    service = _service(
        cohort=_safe_oos_record(),
        errors=[_safe_forecast_error_record()],
    )
    status = service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))

    outcome = status["researchOutcomeOos"]
    assert outcome["status"] == "research_outcome_oos_evidence_available"
    assert outcome["cohortHash"] == "a" * 64
    assert outcome["observationCount"] == 1
    assert outcome["distinctResolvedIssuerCount"] == 1
    assert outcome["productionLearningEligible"] is False

    forecast = status["researchForecastErrorOos"]
    assert forecast["status"] == "forecast_error_oos_evidence_available"
    assert forecast["cohortHash"] == outcome["cohortHash"]
    assert forecast["forecastErrorCount"] == 1
    assert forecast["eligibleOutcomeCount"] == 1
    assert forecast["measurementCoverage"] == 1.0
    assert forecast["distinctResolvedIssuerCount"] == 1
    metrics = forecast["horizons"][str(HORIZON_SECONDS)]["metrics"]
    assert metrics["meanSignedError"] == pytest.approx(-0.02)
    assert metrics["meanAbsoluteError"] == pytest.approx(0.02)
    assert metrics["meanSquaredError"] == pytest.approx(0.0004)
    assert metrics["rootMeanSquaredError"] == pytest.approx(0.02)
    assert forecast["productionEligible"] is False
    assert forecast["isWeightingReady"] is False
    assert forecast["productionLearningEligible"] is False
    assert forecast["policy"]["learningUse"] == "diagnostic_only_not_automatic_model_update"
    assert forecast["policy"]["skillClaim"] == "forbidden_descriptive_errors_are_not_proof_of_predictive_skill"
    assert forecast["policy"]["thresholds"] == "none_selected_here"


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("advisoryStatus", "buy"),
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
    ],
)
def test_learning_status_rejects_unsafe_shadow_contract(field, unsafe_value) -> None:
    payload = _safe_shadow_payload()
    payload[field] = unsafe_value
    service = _service(shadow=FakeShadowLongitudinalService(payload))
    with pytest.raises(ValueError):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "field",
    ["automaticModelMutation", "automaticProductionPromotion", "automaticTrading"],
)
def test_learning_status_rejects_unsafe_shadow_policy(field) -> None:
    payload = _safe_shadow_payload()
    payload["policy"][field] = True
    service = _service(shadow=FakeShadowLongitudinalService(payload))
    with pytest.raises(ValueError):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


def test_learning_status_rejects_unsafe_oos_diagnostic_policy() -> None:
    service = _service(cohort=_safe_oos_record(), errors=[])
    original = service._research_outcome_oos_status

    def unsafe_status(*, record):
        result = original(record=record)
        result["policy"]["automaticModelMutation"] = True
        return result

    service._research_outcome_oos_status = unsafe_status
    with pytest.raises(ValueError, match="mutar modelos"):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


def test_learning_status_rejects_unsafe_forecast_error_oos_contract() -> None:
    service = _service(cohort=_safe_oos_record(), errors=[_safe_forecast_error_record()])
    original = service._research_forecast_error_oos_status

    def unsafe_status(*, as_of, cohort_record):
        result = original(as_of=as_of, cohort_record=cohort_record)
        result["policy"]["skillClaim"] = "claimed"
        return result

    service._research_forecast_error_oos_status = unsafe_status
    with pytest.raises(ValueError, match="skill"):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))

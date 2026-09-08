from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


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


def _safe_oos_record():
    return {
        "cohort_hash": "a" * 64,
        "artifact": {
            "cohortId": "cohort-1",
            "cohortHash": "a" * 64,
            "asOf": "2026-08-31T12:00:00+00:00",
            "observationCount": 4,
            "distinctResolvedIssuerCount": 3,
            "unresolvedIssuerObservationCount": 1,
            "horizonCount": 1,
            "horizons": {
                "2592000": {
                    "horizonSeconds": 2592000,
                    "horizonDays": 30,
                    "observationCount": 4,
                    "resolvedIssuerObservationCount": 3,
                    "unresolvedIssuerObservationCount": 1,
                    "distinctResolvedIssuerCount": 3,
                    "maximumObservationsPerResolvedIssuer": 1,
                    "metrics": {
                        "meanTotalReturn": 0.02,
                        "meanResidualReturn": 0.001,
                    },
                }
            },
        },
    }


def test_learning_status_is_safe_on_empty_history(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    status = RecommendationLearningStatusService(
        database=database
    ).get_status(
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert status["status"] == "learning_diagnostics_only"
    assert status["performance"]["sampleCount"] == 0
    assert status["calibration"]["autoApply"] is False
    assert status["evaluationSchedule"]["dueCount"] == 0
    assert status["drift"] is None
    assert status["shadowLiveLongitudinal"]["persistedCandidateCount"] == 0
    assert status["shadowLiveLongitudinal"]["evaluatedObservationCount"] == 0
    assert status["shadowLiveLongitudinal"]["advisoryStatus"] == "no_advice"
    assert status["shadowLiveLongitudinal"]["productionEligible"] is False
    assert status["researchOutcomeOos"]["status"] == "research_outcome_oos_evidence_pending"
    assert status["researchOutcomeOos"]["productionLearningEligible"] is False
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

    without_horizon = service.get_status(
        as_of=as_of,
        model_version="v1",
    )
    with_filter = service.get_status(
        as_of=as_of,
        model_version="v1",
        horizon_days=30,
    )

    assert without_horizon["drift"] is None
    assert with_filter["drift"] is not None
    assert with_filter["drift"]["status"] == "insufficient_sample"
    assert with_filter["filters"] == {
        "modelVersion": "v1",
        "horizonDays": 30,
    }
    assert with_filter["shadowLiveLongitudinal"]["requestedHorizons"] == [30]


def test_learning_status_passes_same_cutoff_to_shadow_and_oos_read() -> None:
    payload = _safe_shadow_payload()
    shadow = FakeShadowLongitudinalService(payload)
    oos = FakeOosCohortRepository()
    as_of = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=shadow,
        research_outcome_oos_cohort_repository=oos,
    )

    status = service.get_status(as_of=as_of, horizon_days=90)

    assert shadow.calls == [{"as_of": as_of, "horizons": (90,)}]
    assert oos.calls == [as_of]
    assert status["shadowLiveLongitudinal"] is payload
    assert status["researchOutcomeOos"]["status"] == "research_outcome_oos_evidence_pending"


def test_learning_status_surfaces_verified_oos_summary_without_learning_promotion() -> None:
    oos = FakeOosCohortRepository(_safe_oos_record())
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=FakeShadowLongitudinalService(_safe_shadow_payload()),
        research_outcome_oos_cohort_repository=oos,
    )

    status = service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))
    evidence = status["researchOutcomeOos"]

    assert evidence["status"] == "research_outcome_oos_evidence_available"
    assert evidence["cohortHash"] == "a" * 64
    assert evidence["observationCount"] == 4
    assert evidence["distinctResolvedIssuerCount"] == 3
    assert evidence["unresolvedIssuerObservationCount"] == 1
    assert evidence["horizons"]["2592000"]["horizonDays"] == 30
    assert evidence["horizons"]["2592000"]["metrics"]["meanTotalReturn"] == 0.02
    assert evidence["productionEligible"] is False
    assert evidence["isWeightingReady"] is False
    assert evidence["recommendationCandidateReady"] is False
    assert evidence["productionLearningEligible"] is False
    assert evidence["policy"]["learningUse"] == "diagnostic_only_not_automatic_model_update"
    assert evidence["policy"]["automaticModelMutation"] is False


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
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=FakeShadowLongitudinalService(payload),
        research_outcome_oos_cohort_repository=FakeOosCohortRepository(),
    )

    with pytest.raises(ValueError):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "field",
    ["automaticModelMutation", "automaticProductionPromotion", "automaticTrading"],
)
def test_learning_status_rejects_unsafe_shadow_policy(field) -> None:
    payload = _safe_shadow_payload()
    payload["policy"][field] = True
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=FakeShadowLongitudinalService(payload),
        research_outcome_oos_cohort_repository=FakeOosCohortRepository(),
    )

    with pytest.raises(ValueError):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


def test_learning_status_rejects_unsafe_oos_diagnostic_policy() -> None:
    record = _safe_oos_record()
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=FakeShadowLongitudinalService(_safe_shadow_payload()),
        research_outcome_oos_cohort_repository=FakeOosCohortRepository(record),
    )
    original = service._research_outcome_oos_status

    def unsafe_status(*, as_of):
        result = original(as_of=as_of)
        result["policy"]["automaticModelMutation"] = True
        return result

    service._research_outcome_oos_status = unsafe_status
    with pytest.raises(ValueError, match="mutar modelos"):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))

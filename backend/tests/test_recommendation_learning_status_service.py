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
    assert status["advisoryStatus"] == "no_advice"
    assert status["productionEligible"] is False
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


def test_learning_status_passes_same_cutoff_and_requested_horizon_to_shadow() -> None:
    payload = _safe_shadow_payload()
    shadow = FakeShadowLongitudinalService(payload)
    as_of = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)
    service = RecommendationLearningStatusService(
        shadow_longitudinal_service=shadow,
    )

    status = service.get_status(as_of=as_of, horizon_days=90)

    assert shadow.calls == [{"as_of": as_of, "horizons": (90,)}]
    assert status["shadowLiveLongitudinal"] is payload


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
    )

    with pytest.raises(ValueError):
        service.get_status(as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))

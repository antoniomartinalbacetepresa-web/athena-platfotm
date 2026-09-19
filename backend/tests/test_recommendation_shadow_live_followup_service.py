from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_followup_service import (
    RecommendationShadowLiveFollowupService,
)


class FakeCandidateRepository:
    def __init__(self, row):
        self.row = row

    def get(self, candidate_id):
        return self.row


class FakeOutcomeService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeEvaluationService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


def _outcome_progress():
    return {
        "status": "shadow_outcomes_evaluated",
        "snapshotId": 10,
        "advisoryStatus": "no_advice",
    }


def _evaluation():
    return {
        "status": "shadow_live_candidate_outcomes_evaluated",
        "candidateId": 20,
        "snapshotId": 10,
        "asOf": "2025-07-03T00:00:00+00:00",
        "evaluatedHorizonCount": 2,
        "metrics": {"mse": 0.01, "mae": 0.08, "signAccuracy": 0.5},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def test_followup_matures_outcomes_before_scoring_persisted_prediction():
    outcomes = FakeOutcomeService(_outcome_progress())
    evaluation = FakeEvaluationService(_evaluation())
    service = RecommendationShadowLiveFollowupService(
        candidate_repository=FakeCandidateRepository({"id": 20, "snapshot_id": 10}),
        outcome_service=outcomes,
        evaluation_service=evaluation,
    )
    as_of = datetime(2025, 7, 3, tzinfo=timezone.utc)

    result = service.run(candidate_id=20, as_of=as_of, horizons=(7, 30))

    assert outcomes.calls == [
        {"snapshot_id": 10, "as_of": as_of, "horizons": (7, 30)}
    ]
    assert evaluation.calls == [{"candidate_id": 20, "as_of": as_of}]
    assert result["status"] == "shadow_live_followup_completed"
    assert result["evaluatedHorizonCount"] == 2
    assert result["metrics"]["signAccuracy"] == 0.5
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False


def test_followup_rejects_missing_candidate():
    service = RecommendationShadowLiveFollowupService(
        candidate_repository=FakeCandidateRepository(None),
        outcome_service=FakeOutcomeService(_outcome_progress()),
        evaluation_service=FakeEvaluationService(_evaluation()),
    )

    with pytest.raises(ValueError, match="no existe"):
        service.run(
            candidate_id=20,
            as_of=datetime(2025, 7, 3, tzinfo=timezone.utc),
        )


def test_followup_fails_closed_if_outcome_layer_assigns_advice():
    outcome = _outcome_progress()
    outcome["advisoryStatus"] = "advice"
    evaluation = FakeEvaluationService(_evaluation())
    service = RecommendationShadowLiveFollowupService(
        candidate_repository=FakeCandidateRepository({"id": 20, "snapshot_id": 10}),
        outcome_service=FakeOutcomeService(outcome),
        evaluation_service=evaluation,
    )

    with pytest.raises(ValueError, match="advisoryStatus=no_advice"):
        service.run(
            candidate_id=20,
            as_of=datetime(2025, 7, 3, tzinfo=timezone.utc),
        )
    assert evaluation.calls == []


def test_followup_fails_closed_if_evaluation_changes_snapshot():
    evaluation = _evaluation()
    evaluation["snapshotId"] = 999
    service = RecommendationShadowLiveFollowupService(
        candidate_repository=FakeCandidateRepository({"id": 20, "snapshot_id": 10}),
        outcome_service=FakeOutcomeService(_outcome_progress()),
        evaluation_service=FakeEvaluationService(evaluation),
    )

    with pytest.raises(RuntimeError, match="cambió el snapshot"):
        service.run(
            candidate_id=20,
            as_of=datetime(2025, 7, 3, tzinfo=timezone.utc),
        )


def test_followup_does_not_allow_evaluation_to_enable_recommendations():
    evaluation = _evaluation()
    evaluation["recommendationCandidateReady"] = True
    service = RecommendationShadowLiveFollowupService(
        candidate_repository=FakeCandidateRepository({"id": 20, "snapshot_id": 10}),
        outcome_service=FakeOutcomeService(_outcome_progress()),
        evaluation_service=FakeEvaluationService(evaluation),
    )

    with pytest.raises(ValueError, match="no puede habilitar"):
        service.run(
            candidate_id=20,
            as_of=datetime(2025, 7, 3, tzinfo=timezone.utc),
        )

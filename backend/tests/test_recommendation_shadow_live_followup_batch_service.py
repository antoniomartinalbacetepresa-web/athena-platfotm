from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_followup_batch_service import (
    RecommendationShadowLiveFollowupBatchService,
)


class FakeCandidateRepository:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def list_all(self):
        self.calls += 1
        return list(self.rows)


class FakeFollowupService:
    def __init__(self, *, evaluated_by_candidate=None, violation=None):
        self.evaluated_by_candidate = evaluated_by_candidate or {}
        self.violation = violation
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        candidate_id = kwargs["candidate_id"]
        payload = {
            "status": "shadow_live_followup_completed",
            "candidateId": candidate_id,
            "snapshotId": candidate_id + 100,
            "asOf": kwargs["as_of"].isoformat(),
            "evaluatedHorizonCount": self.evaluated_by_candidate.get(candidate_id, 0),
            "metrics": None,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }
        if self.violation == "advice":
            payload["advisoryStatus"] = "buy"
        elif self.violation == "production":
            payload["productionEligible"] = True
        elif self.violation == "recommendation":
            payload["recommendationCandidateReady"] = True
        elif self.violation == "promotion":
            payload["policy"]["automaticProductionPromotion"] = True
        elif self.violation == "trading":
            payload["policy"]["automaticTrading"] = True
        elif self.violation == "candidate_id":
            payload["candidateId"] = candidate_id + 1
        elif self.violation == "count_bool":
            payload["evaluatedHorizonCount"] = True
        return payload


def _as_of():
    return datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)


def test_batch_discovers_every_persisted_candidate_once_and_uses_one_pit_cutoff():
    repository = FakeCandidateRepository([{"id": 4}, {"id": 9}, {"id": 15}])
    followup = FakeFollowupService(evaluated_by_candidate={4: 2, 9: 0, 15: 1})
    service = RecommendationShadowLiveFollowupBatchService(
        candidate_repository=repository,
        followup_service=followup,
    )

    result = service.run(as_of=_as_of())

    assert repository.calls == 1
    assert [call["candidate_id"] for call in followup.calls] == [4, 9, 15]
    assert all(call["as_of"] == _as_of() for call in followup.calls)
    assert all(call["horizons"] == (7, 30, 90, 180, 365) for call in followup.calls)
    assert result["candidateCount"] == 3
    assert result["processedCandidateCount"] == 3
    assert result["candidatesWithEvaluatedOutcomes"] == 2
    assert result["candidatesPendingOutcomes"] == 1
    assert result["evaluatedHorizonCount"] == 3
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["policy"]["automaticTrading"] is False


def test_batch_is_honest_when_no_live_candidates_exist():
    service = RecommendationShadowLiveFollowupBatchService(
        candidate_repository=FakeCandidateRepository([]),
        followup_service=FakeFollowupService(),
    )

    result = service.run(as_of=_as_of(), horizons=(30, 90))

    assert result["candidateCount"] == 0
    assert result["processedCandidateCount"] == 0
    assert result["evaluatedHorizonCount"] == 0
    assert result["followups"] == []
    assert result["horizons"] == [30, 90]


def test_batch_rejects_naive_cutoff_and_invalid_horizons_before_followup():
    followup = FakeFollowupService()
    service = RecommendationShadowLiveFollowupBatchService(
        candidate_repository=FakeCandidateRepository([{"id": 1}]),
        followup_service=followup,
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.run(as_of=datetime(2026, 9, 4, 6, 0))

    for horizons in ((), (0,), (30, 30), (True,), (30, -1)):
        with pytest.raises(ValueError):
            service.run(as_of=_as_of(), horizons=horizons)

    assert followup.calls == []


def test_batch_rejects_invalid_persisted_candidate_identity():
    for value in (0, -1, True, "7", None):
        followup = FakeFollowupService()
        service = RecommendationShadowLiveFollowupBatchService(
            candidate_repository=FakeCandidateRepository([{"id": value}]),
            followup_service=followup,
        )
        with pytest.raises(ValueError, match="candidate.id"):
            service.run(as_of=_as_of())
        assert followup.calls == []


def test_batch_fails_closed_on_followup_policy_or_identity_escalation():
    for violation in (
        "advice",
        "production",
        "recommendation",
        "promotion",
        "trading",
        "candidate_id",
        "count_bool",
    ):
        service = RecommendationShadowLiveFollowupBatchService(
            candidate_repository=FakeCandidateRepository([{"id": 5}]),
            followup_service=FakeFollowupService(violation=violation),
        )
        with pytest.raises((ValueError, RuntimeError)):
            service.run(as_of=_as_of())

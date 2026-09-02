from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)


class FakeCandidateRepository:
    def __init__(self, stored):
        self.stored = stored

    def get(self, candidate_id):
        return deepcopy(self.stored)


class FakeSnapshotRepository:
    def __init__(self, snapshot, outcomes):
        self.snapshot = snapshot
        self.outcomes = outcomes

    def get_snapshot(self, snapshot_id):
        return deepcopy(self.snapshot)

    def list_outcomes(self, snapshot_id):
        return deepcopy(self.outcomes)


class FakeCandidateService:
    def validate_artifact(self, artifact):
        return artifact


def _candidate():
    return {
        "status": "shadow_live_candidate_inferred",
        "candidateFingerprint": "c" * 64,
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
        "horizons": {
            "7": {
                "horizonDays": 7,
                "expectedExcessReturn": 0.10,
            },
            "30": {
                "horizonDays": 30,
                "expectedExcessReturn": -0.02,
            },
            "90": {
                "horizonDays": 90,
                "expectedExcessReturn": None,
            },
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _stored(candidate=None):
    return {
        "id": 20,
        "snapshot_id": 10,
        "artifact": deepcopy(candidate or _candidate()),
    }


def _benchmark_evidence(*, due_at: str, evaluated_at: str):
    return {
        "status": "resolved",
        "benchmarkSymbol": "SPY",
        "benchmarkInstrumentId": 44,
        "entryPrice": 100.0,
        "exitPrice": 101.0,
        "benchmarkReturn": 0.01,
        "entryObservedAt": "2025-06-01T00:00:00+00:00",
        "exitObservedAt": due_at,
        "entryRetrievedAt": "2025-06-01T00:01:00+00:00",
        "exitRetrievedAt": evaluated_at,
        "entrySourceProvider": "benchmark_test",
        "exitSourceProvider": "benchmark_test",
    }


def _outcome(horizon, *, excess, evaluated_at, due_at=None):
    due = due_at or evaluated_at
    return {
        "horizon_days": horizon,
        "due_at": due,
        "evaluated_at": evaluated_at,
        "excess_return": excess,
        "benchmark_return": 0.01,
        "realized_return": excess + 0.01,
        "benchmark_evidence": _benchmark_evidence(
            due_at=due,
            evaluated_at=evaluated_at,
        ),
    }


def _service(*, candidate=None, outcomes=None, stored=None, snapshot=None):
    return RecommendationShadowLiveCandidateEvaluationService(
        candidate_repository=FakeCandidateRepository(
            _stored(candidate) if stored is None else stored
        ),
        snapshot_repository=FakeSnapshotRepository(
            {"id": 10, "benchmark_symbol": "SPY"}
            if snapshot is None
            else snapshot,
            [] if outcomes is None else outcomes,
        ),
        candidate_service=FakeCandidateService(),
    )


def test_evaluates_only_matured_predictions_and_computes_error_metrics():
    outcomes = [
        _outcome(
            7,
            excess=0.04,
            due_at="2025-06-08T00:00:00+00:00",
            evaluated_at="2025-06-09T00:00:00+00:00",
        ),
        _outcome(
            30,
            excess=0.01,
            due_at="2025-07-01T00:00:00+00:00",
            evaluated_at="2025-07-02T00:00:00+00:00",
        ),
    ]
    result = _service(outcomes=outcomes).evaluate(
        candidate_id=20,
        as_of=datetime(2025, 7, 3, tzinfo=timezone.utc),
    )

    assert result["status"] == "shadow_live_candidate_outcomes_evaluated"
    assert result["evaluatedHorizonCount"] == 2
    assert result["frozenBenchmarkSymbol"] == "SPY"
    assert result["horizons"]["7"]["predictionError"] == pytest.approx(0.06)
    assert result["horizons"]["7"]["directionCorrect"] is True
    assert result["horizons"]["7"]["benchmarkEvidence"]["benchmarkSymbol"] == "SPY"
    assert result["horizons"]["30"]["predictionError"] == pytest.approx(-0.03)
    assert result["horizons"]["30"]["directionCorrect"] is False
    assert result["horizons"]["90"]["status"] == "not_evaluable_no_live_prediction"
    assert result["metrics"]["mse"] == pytest.approx(0.00225)
    assert result["metrics"]["mae"] == pytest.approx(0.045)
    assert result["metrics"]["signAccuracy"] == pytest.approx(0.5)
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False


def test_future_evaluated_outcome_is_not_used_before_as_of():
    outcomes = [
        _outcome(
            7,
            excess=0.04,
            due_at="2025-06-08T00:00:00+00:00",
            evaluated_at="2025-06-20T00:00:00+00:00",
        )
    ]
    service = _service(outcomes=outcomes)

    early = service.evaluate(
        candidate_id=20,
        as_of=datetime(2025, 6, 15, tzinfo=timezone.utc),
    )
    later = service.evaluate(
        candidate_id=20,
        as_of=datetime(2025, 6, 21, tzinfo=timezone.utc),
    )

    assert early["evaluatedHorizonCount"] == 0
    assert early["metrics"] is None
    assert early["horizons"]["7"]["status"] == "pending_outcome_not_mature_at_as_of"
    assert later["evaluatedHorizonCount"] == 1
    assert later["horizons"]["7"]["status"] == "evaluated"


def test_missing_outcome_remains_pending():
    result = _service(outcomes=[]).evaluate(
        candidate_id=20,
        as_of=datetime(2025, 8, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "shadow_live_candidate_outcomes_pending"
    assert result["horizons"]["7"]["status"] == "pending_outcome"
    assert result["horizons"]["30"]["status"] == "pending_outcome"


def test_as_of_before_candidate_is_rejected():
    with pytest.raises(ValueError, match="anterior al candidato"):
        _service().evaluate(
            candidate_id=20,
            as_of=datetime(2025, 5, 31, tzinfo=timezone.utc),
        )


def test_non_finite_realized_excess_return_is_rejected():
    outcomes = [
        _outcome(
            7,
            excess=float("nan"),
            evaluated_at="2025-06-09T00:00:00+00:00",
        )
    ]
    with pytest.raises(ValueError, match="excess_return debe ser finito"):
        _service(outcomes=outcomes).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_unprovenanced_excess_outcome_is_rejected():
    outcome = _outcome(
        7,
        excess=0.01,
        evaluated_at="2025-06-09T00:00:00+00:00",
    )
    outcome["benchmark_evidence"] = None

    with pytest.raises(ValueError, match="evidencia trazable"):
        _service(outcomes=[outcome]).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_outcome_from_different_benchmark_is_rejected():
    outcome = _outcome(
        7,
        excess=0.01,
        evaluated_at="2025-06-09T00:00:00+00:00",
    )
    outcome["benchmark_evidence"]["benchmarkSymbol"] = "QQQ"

    with pytest.raises(ValueError, match="otro benchmark"):
        _service(outcomes=[outcome]).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_duplicate_persisted_outcome_horizon_is_rejected():
    outcome = _outcome(
        7,
        excess=0.01,
        evaluated_at="2025-06-09T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="más de un outcome"):
        _service(outcomes=[outcome, outcome]).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_candidate_horizon_key_and_payload_must_match():
    candidate = _candidate()
    candidate["horizons"]["7"]["horizonDays"] = 30

    with pytest.raises(ValueError, match="identidad de horizonte"):
        _service(candidate=candidate).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_candidate_attempting_production_fails_closed():
    candidate = _candidate()
    candidate["productionEligible"] = True

    with pytest.raises(ValueError, match="productionEligible=False"):
        _service(candidate=candidate).evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )


def test_missing_candidate_is_rejected():
    service = _service(stored=None)
    service._candidate_repository.stored = None

    with pytest.raises(ValueError, match="no existe"):
        service.evaluate(
            candidate_id=20,
            as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
        )

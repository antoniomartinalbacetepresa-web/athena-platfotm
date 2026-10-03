from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_uncertainty_service import (
    RecommendationShadowLiveUncertaintyService,
)


MODEL = "a" * 64
OTHER_MODEL = "b" * 64


class FakeRepository:
    def __init__(self, rows):
        self.rows = {row["id"]: deepcopy(row) for row in rows}

    def get(self, candidate_id):
        row = self.rows.get(candidate_id)
        return deepcopy(row) if row is not None else None

    def list_all(self):
        return [deepcopy(self.rows[key]) for key in sorted(self.rows)]


class FakeCandidateService:
    def validate_artifact(self, artifact):
        return deepcopy(artifact)


class FakeEvaluationService:
    def __init__(self, evaluations):
        self.evaluations = evaluations
        self.calls = []

    def evaluate(self, *, candidate_id, as_of):
        self.calls.append((candidate_id, as_of))
        return deepcopy(self.evaluations[candidate_id])


def _fingerprint(candidate_id):
    return f"{candidate_id + 1000:064x}"[-64:]


def _artifact(
    candidate_id,
    *,
    as_of,
    symbol="TEST",
    model=MODEL,
    expected=0.03,
):
    return {
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": _fingerprint(candidate_id),
        "confirmationEvidenceFingerprint": f"{candidate_id + 2000:064x}"[-64:],
        "symbol": symbol,
        "asOf": as_of,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "modelFingerprint": model,
                "expectedExcessReturn": expected,
            }
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "action": None,
        "score": None,
        "conviction": None,
    }


def _row(candidate_id, **kwargs):
    artifact = _artifact(candidate_id, **kwargs)
    return {
        "id": candidate_id,
        "candidate_fingerprint": artifact["candidateFingerprint"],
        "artifact": artifact,
    }


def _evaluation(candidate_id, *, expected, realized, production=False):
    return {
        "candidateFingerprint": _fingerprint(candidate_id),
        "horizons": {
            "7": {
                "horizonDays": 7,
                "status": "evaluated",
                "expectedExcessReturn": expected,
                "realizedExcessReturn": realized,
            }
        },
        "advisoryStatus": "no_advice",
        "productionEligible": production,
        "recommendationCandidateReady": False,
    }


def _service(rows, evaluations, *, minimum=2):
    evaluator = FakeEvaluationService(evaluations)
    return (
        RecommendationShadowLiveUncertaintyService(
            candidate_repository=FakeRepository(rows),
            candidate_service=FakeCandidateService(),
            evaluation_service=evaluator,
            minimum_observations=minimum,
        ),
        evaluator,
    )


def test_builds_empirical_scenarios_only_from_prior_non_overlapping_same_model_residuals():
    rows = [
        _row(1, as_of="2025-01-01T00:00:00+00:00", expected=0.02),
        _row(2, as_of="2025-01-05T00:00:00+00:00", expected=0.04),
        _row(3, as_of="2025-01-08T00:00:00+00:00", expected=-0.01),
        _row(10, as_of="2025-01-20T00:00:00+00:00", expected=0.03),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.02, realized=0.01),
        2: _evaluation(2, expected=0.04, realized=0.50),
        3: _evaluation(3, expected=-0.01, realized=0.01),
    }
    service, evaluator = _service(rows, evaluations)

    result = service.evaluate(candidate_id=10)

    horizon = result["horizons"]["7"]
    assert result["status"] == "shadow_live_empirical_uncertainty_available"
    assert horizon["availableObservationCount"] == 3
    assert horizon["observationCount"] == 2
    assert horizon["residualMetrics"]["mean"] == pytest.approx(0.005)
    assert horizon["residualMetrics"]["p50"] == pytest.approx(0.005)
    assert horizon["scenarios"]["medianEmpiricalExcessReturn"] == pytest.approx(0.035)
    assert horizon["independenceStatus"] == "calendar_horizon_non_overlapping_forecast_origins"
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["conviction"] is None
    assert [candidate_id for candidate_id, _ in evaluator.calls] == [1, 2, 3]
    assert all(
        as_of == datetime(2025, 1, 20, tzinfo=timezone.utc)
        for _, as_of in evaluator.calls
    )


def test_later_candidate_and_current_candidate_are_never_used_as_prior_evidence():
    rows = [
        _row(1, as_of="2025-01-01T00:00:00+00:00"),
        _row(10, as_of="2025-01-20T00:00:00+00:00"),
        _row(11, as_of="2025-01-21T00:00:00+00:00"),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.03, realized=0.02),
        10: _evaluation(10, expected=0.03, realized=1.00),
        11: _evaluation(11, expected=0.03, realized=1.00),
    }
    service, evaluator = _service(rows, evaluations, minimum=2)

    result = service.evaluate(candidate_id=10)

    assert result["status"] == "shadow_live_empirical_uncertainty_pending"
    assert result["horizons"]["7"]["observationCount"] == 1
    assert [candidate_id for candidate_id, _ in evaluator.calls] == [1]


def test_other_symbol_and_other_model_do_not_enter_uncertainty_series():
    rows = [
        _row(1, as_of="2025-01-01T00:00:00+00:00", symbol="OTHER"),
        _row(2, as_of="2025-01-01T00:00:00+00:00", model=OTHER_MODEL),
        _row(3, as_of="2025-01-01T00:00:00+00:00", model=MODEL),
        _row(10, as_of="2025-01-20T00:00:00+00:00", model=MODEL),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.03, realized=0.10),
        2: _evaluation(2, expected=0.03, realized=0.10),
        3: _evaluation(3, expected=0.03, realized=0.02),
    }
    service, evaluator = _service(rows, evaluations, minimum=2)

    result = service.evaluate(candidate_id=10)

    assert result["horizons"]["7"]["observationCount"] == 1
    assert [candidate_id for candidate_id, _ in evaluator.calls] == [3]


def test_no_live_prediction_has_no_scenarios():
    row = _row(10, as_of="2025-01-20T00:00:00+00:00", expected=None)
    service, evaluator = _service([row], {}, minimum=2)

    result = service.evaluate(candidate_id=10)

    assert result["horizons"]["7"]["status"] == "not_applicable_no_live_prediction"
    assert result["horizons"]["7"]["scenarios"] is None
    assert evaluator.calls == []


def test_persisted_fingerprint_mismatch_fails_closed():
    row = _row(10, as_of="2025-01-20T00:00:00+00:00")
    row["candidate_fingerprint"] = "e" * 64
    service, _ = _service([row], {}, minimum=2)

    with pytest.raises(ValueError, match="fingerprint persistido"):
        service.evaluate(candidate_id=10)


def test_prior_evaluation_attempting_production_fails_closed():
    rows = [
        _row(1, as_of="2025-01-01T00:00:00+00:00"),
        _row(10, as_of="2025-01-20T00:00:00+00:00"),
    ]
    service, _ = _service(
        rows,
        {1: _evaluation(1, expected=0.03, realized=0.02, production=True)},
        minimum=2,
    )

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(candidate_id=10)


def test_invalid_minimum_and_unknown_candidate_are_rejected():
    with pytest.raises(ValueError, match="al menos 2"):
        RecommendationShadowLiveUncertaintyService(minimum_observations=1)

    service, _ = _service([], {}, minimum=2)
    with pytest.raises(ValueError, match="no existe"):
        service.evaluate(candidate_id=99)

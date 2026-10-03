from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_longitudinal_service import (
    RecommendationShadowLiveLongitudinalService,
)


class FakeCandidateRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_all(self):
        return deepcopy(self.rows)


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


def _artifact(
    candidate_id,
    *,
    symbol="TEST",
    as_of="2025-06-01T00:00:00+00:00",
    model_7=None,
    confirmation=None,
):
    model = model_7 or (f"{candidate_id:064x}"[-64:])
    confirmation_fp = confirmation or (f"{candidate_id + 100:064x}"[-64:])
    fingerprint = f"{candidate_id + 200:064x}"[-64:]
    return {
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": fingerprint,
        "confirmationEvidenceFingerprint": confirmation_fp,
        "symbol": symbol,
        "asOf": as_of,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "modelFingerprint": model,
                "expectedExcessReturn": 0.05,
            },
            "30": {
                "horizonDays": 30,
                "modelFingerprint": "f" * 64,
                "expectedExcessReturn": None,
            },
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


def _evaluation(candidate_id, *, expected, realized, symbol="TEST", status="evaluated"):
    fingerprint = f"{candidate_id + 200:064x}"[-64:]
    horizon = {
        "horizonDays": 7,
        "status": status,
        "expectedExcessReturn": expected,
    }
    if status == "evaluated":
        horizon.update(
            {
                "realizedExcessReturn": realized,
                "predictionError": expected - realized,
            }
        )
    return {
        "candidateId": candidate_id,
        "candidateFingerprint": fingerprint,
        "symbol": symbol,
        "horizons": {"7": horizon},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _service(rows, evaluations):
    evaluation_service = FakeEvaluationService(evaluations)
    return (
        RecommendationShadowLiveLongitudinalService(
            candidate_repository=FakeCandidateRepository(rows),
            evaluation_service=evaluation_service,
            candidate_service=FakeCandidateService(),
        ),
        evaluation_service,
    )


def test_aggregates_mature_forward_predictions_for_same_frozen_model():
    model = "a" * 64
    rows = [
        _row(1, model_7=model, as_of="2025-06-01T00:00:00+00:00"),
        _row(2, model_7=model, as_of="2025-06-02T00:00:00+00:00"),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.10, realized=0.05),
        2: _evaluation(2, expected=-0.02, realized=0.01),
    }
    service, _ = _service(rows, evaluations)

    result = service.evaluate(
        as_of=datetime(2025, 7, 15, tzinfo=timezone.utc),
        horizons=(7,),
    )

    horizon = result["horizons"]["7"]
    metrics = horizon["models"][model]["metrics"]
    assert result["status"] == "shadow_live_longitudinal_evidence_available"
    assert result["evaluatedObservationCount"] == 2
    assert horizon["comparabilityStatus"] == "single_frozen_model_series"
    assert metrics["mse"] == pytest.approx((0.05**2 + (-0.03) ** 2) / 2)
    assert metrics["mae"] == pytest.approx(0.04)
    assert metrics["bias"] == pytest.approx(0.01)
    assert metrics["signAccuracy"] == pytest.approx(0.5)
    assert metrics["zeroExcessBaselineMse"] == pytest.approx((0.05**2 + 0.01**2) / 2)
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["productionEligible"] is False


def test_different_frozen_models_are_never_pooled_into_one_metric_series():
    rows = [
        _row(1, model_7="a" * 64),
        _row(2, model_7="b" * 64),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.02, realized=0.01),
        2: _evaluation(2, expected=0.40, realized=-0.20),
    }
    service, _ = _service(rows, evaluations)

    result = service.evaluate(
        as_of=datetime(2025, 7, 15, tzinfo=timezone.utc),
        horizons=(7,),
    )

    horizon = result["horizons"]["7"]
    assert horizon["distinctModelCount"] == 2
    assert horizon["comparabilityStatus"] == "mixed_model_versions_not_pooled"
    assert horizon["models"]["a" * 64]["observationCount"] == 1
    assert horizon["models"]["b" * 64]["observationCount"] == 1
    assert "metrics" not in horizon


def test_future_candidate_is_excluded_before_calling_evaluation_service():
    rows = [_row(1, as_of="2025-08-01T00:00:00+00:00")]
    service, evaluator = _service(
        rows,
        {1: _evaluation(1, expected=0.01, realized=0.02)},
    )

    result = service.evaluate(
        as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizons=(7,),
    )

    assert result["status"] == "shadow_live_longitudinal_evidence_pending"
    assert result["skippedFutureCandidateCount"] == 1
    assert evaluator.calls == []


def test_symbol_filter_does_not_mix_issuers():
    rows = [
        _row(1, symbol="AAA"),
        _row(2, symbol="BBB"),
    ]
    evaluations = {
        1: _evaluation(1, expected=0.01, realized=0.02, symbol="AAA"),
        2: _evaluation(2, expected=0.90, realized=-0.90, symbol="BBB"),
    }
    service, evaluator = _service(rows, evaluations)

    result = service.evaluate(
        as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
        symbol="aaa",
        horizons=(7,),
    )

    assert result["symbol"] == "AAA"
    assert result["evaluatedCandidateCount"] == 1
    assert [candidate_id for candidate_id, _ in evaluator.calls] == [1]


def test_pending_outcome_is_not_counted_as_forward_evidence():
    rows = [_row(1)]
    evaluations = {
        1: _evaluation(
            1,
            expected=0.01,
            realized=0.0,
            status="pending_outcome",
        )
    }
    service, _ = _service(rows, evaluations)

    result = service.evaluate(
        as_of=datetime(2025, 6, 2, tzinfo=timezone.utc),
        horizons=(7,),
    )

    assert result["evaluatedObservationCount"] == 0
    assert result["horizons"]["7"]["comparabilityStatus"] == "no_mature_live_evidence"


def test_persisted_fingerprint_mismatch_fails_closed():
    row = _row(1)
    row["candidate_fingerprint"] = "e" * 64
    service, _ = _service(
        [row],
        {1: _evaluation(1, expected=0.01, realized=0.01)},
    )

    with pytest.raises(ValueError, match="fingerprint persistido"):
        service.evaluate(
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizons=(7,),
        )


def test_naive_as_of_and_duplicate_horizons_are_rejected():
    service, _ = _service([], {})

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(as_of=datetime(2025, 7, 1), horizons=(7,))
    with pytest.raises(ValueError, match="no pueden repetirse"):
        service.evaluate(
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizons=(7, 7),
        )


def test_evaluation_attempting_production_fails_closed():
    rows = [_row(1)]
    evaluation = _evaluation(1, expected=0.01, realized=0.02)
    evaluation["productionEligible"] = True
    service, _ = _service(rows, {1: evaluation})

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(
            as_of=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizons=(7,),
        )

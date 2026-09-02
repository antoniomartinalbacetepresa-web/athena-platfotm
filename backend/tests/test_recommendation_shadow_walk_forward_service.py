from datetime import datetime, timezone

from app.services.recommendation_shadow_walk_forward_service import (
    RecommendationShadowWalkForwardService,
)


class FakeCandidateService:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.results[len(self.calls) - 1]


def _dt(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _fold(train_end, validation_end, as_of):
    return {
        "train_end": train_end,
        "validation_end": validation_end,
        "as_of": as_of,
    }


def _evaluated(model_mse, baseline_mse, sign_accuracy=0.6):
    return {
        "status": "shadow_linear_candidate_evaluated",
        "test": {
            "mse": float(model_mse),
            "mae": float(model_mse) ** 0.5,
            "signAccuracy": float(sign_accuracy),
        },
        "zeroExcessReturnBaseline": {
            "mse": float(baseline_mse),
            "mae": float(baseline_mse) ** 0.5,
            "signAccuracy": 0.5,
        },
        "productionEligible": False,
    }


def _folds():
    return [
        _fold(_dt(2024, 1, 1), _dt(2024, 4, 1), _dt(2024, 7, 1)),
        _fold(_dt(2024, 4, 1), _dt(2024, 7, 1), _dt(2024, 10, 1)),
        _fold(_dt(2024, 7, 1), _dt(2024, 10, 1), _dt(2025, 1, 1)),
    ]


def test_walk_forward_aggregates_multiple_out_of_sample_folds() -> None:
    candidate = FakeCandidateService(
        [
            _evaluated(0.008, 0.010, 0.60),
            _evaluated(0.009, 0.010, 0.55),
            _evaluated(0.011, 0.010, 0.52),
        ]
    )
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        minimum_evaluated_folds=3,
    )

    result = service.evaluate(folds=_folds(), horizon_days=30)

    assert result["status"] == "shadow_walk_forward_evaluated"
    assert result["evaluatedFoldCount"] == 3
    assert result["blockedFoldCount"] == 0
    assert result["summary"]["baselineWinRate"] == 2 / 3
    assert result["summary"]["medianRelativeMseImprovement"] > 0
    assert result["summary"]["stableDirectionally"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"]["actions"] == "not_assigned"
    assert all(call["horizon_days"] == 30 for call in candidate.calls)


def test_walk_forward_does_not_call_weak_performance_production_ready() -> None:
    candidate = FakeCandidateService(
        [
            _evaluated(0.012, 0.010),
            _evaluated(0.011, 0.010),
            _evaluated(0.009, 0.010),
        ]
    )
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        minimum_evaluated_folds=3,
    )

    result = service.evaluate(folds=_folds(), horizon_days=90)

    assert result["summary"]["baselineWinRate"] == 1 / 3
    assert result["summary"]["stableDirectionally"] is False
    assert result["productionEligible"] is False


def test_walk_forward_blocks_when_too_few_folds_are_evaluable() -> None:
    candidate = FakeCandidateService(
        [
            _evaluated(0.008, 0.010),
            {"status": "insufficient_shadow_calibration_data"},
            {"status": "insufficient_shadow_calibration_data"},
        ]
    )
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        minimum_evaluated_folds=2,
    )

    result = service.evaluate(folds=_folds(), horizon_days=30)

    assert result["status"] == "insufficient_walk_forward_evidence"
    assert result["evaluatedFoldCount"] == 1
    assert result["blockedFoldCount"] == 2
    assert result["productionEligible"] is False


def test_walk_forward_requires_strictly_increasing_test_boundaries() -> None:
    folds = _folds()
    folds[2]["as_of"] = folds[1]["as_of"]
    service = RecommendationShadowWalkForwardService(
        candidate_service=FakeCandidateService([]),
    )

    try:
        service.evaluate(folds=folds, horizon_days=30)
    except ValueError as exc:
        assert "estrictamente" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de folds no crecientes.")


def test_walk_forward_rejects_naive_datetimes_before_candidate_evaluation() -> None:
    folds = _folds()
    folds[0]["train_end"] = datetime(2024, 1, 1)
    candidate = FakeCandidateService([])
    service = RecommendationShadowWalkForwardService(candidate_service=candidate)

    try:
        service.evaluate(folds=folds, horizon_days=30)
    except ValueError as exc:
        assert "zona horaria" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de timestamp sin zona horaria.")
    assert candidate.calls == []


def test_walk_forward_rejects_non_positive_horizon() -> None:
    service = RecommendationShadowWalkForwardService(
        candidate_service=FakeCandidateService([]),
    )

    try:
        service.evaluate(folds=_folds(), horizon_days=0)
    except ValueError as exc:
        assert "positivo" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de horizonte no positivo.")

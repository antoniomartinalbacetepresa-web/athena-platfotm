from __future__ import annotations

import pytest

from app.services.recommendation_shadow_holdout_gate_service import (
    RecommendationShadowHoldoutGateService,
)


def _holdout(
    horizon: int,
    *,
    rows: int = 30,
    improvement: float = 0.15,
    sign_accuracy: float = 0.6,
    beats: bool = True,
    fingerprint: str | None = None,
):
    return {
        "status": "shadow_independent_holdout_evaluated",
        "horizonDays": horizon,
        "holdoutRowCount": rows,
        "metrics": {"mse": 0.01, "mae": 0.08, "signAccuracy": sign_accuracy},
        "zeroExcessReturnBaseline": {"mse": 0.02, "mae": 0.1, "signAccuracy": 0.5},
        "relativeMseImprovement": improvement,
        "beatsZeroBaselineOnMse": beats,
        "modelFingerprint": fingerprint or f"model-{horizon}",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_gate_requires_multiple_independent_horizons():
    service = RecommendationShadowHoldoutGateService()
    result = service.evaluate(holdouts={7: _holdout(7), 30: _holdout(30)})

    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert "insufficient_evaluated_holdout_horizons" in result["globalReasons"]
    assert result["productionEligible"] is False


def test_gate_allows_only_shadow_threshold_calibration_research():
    service = RecommendationShadowHoldoutGateService()
    result = service.evaluate(
        holdouts={7: _holdout(7), 30: _holdout(30), 90: _holdout(90)}
    )

    assert result["status"] == "shadow_candidate_may_enter_action_threshold_calibration"
    assert result["actionThresholdCalibrationResearchEligible"] is True
    assert result["passingHorizonCount"] == 3
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"]["thresholdsCanBeFitOnTheseHoldouts"] is False
    assert result["policy"]["freshEvidenceRequiredAfterThresholdCalibration"] is True


def test_weak_horizon_is_counted_as_failure_not_ignored():
    service = RecommendationShadowHoldoutGateService()
    result = service.evaluate(
        holdouts={
            7: _holdout(7),
            30: _holdout(30, improvement=-0.1, beats=False, sign_accuracy=0.4),
            90: _holdout(90),
        }
    )

    assert result["evaluatedHorizonCount"] == 3
    assert result["passingHorizonCount"] == 2
    assert result["actionThresholdCalibrationResearchEligible"] is True
    assert result["horizons"]["30"]["passesHoldoutGate"] is False
    assert "does_not_beat_zero_excess_baseline" in result["horizons"]["30"]["reasons"]


def test_small_holdout_sample_cannot_pass_even_with_good_metrics():
    service = RecommendationShadowHoldoutGateService()
    result = service.evaluate(
        holdouts={7: _holdout(7, rows=5), 30: _holdout(30), 90: _holdout(90)}
    )

    assert result["horizons"]["7"]["passesHoldoutGate"] is False
    assert "insufficient_independent_holdout_rows" in result["horizons"]["7"]["reasons"]


def test_contract_violation_is_rejected():
    service = RecommendationShadowHoldoutGateService()
    invalid = _holdout(30)
    invalid["productionEligible"] = True

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(holdouts={30: invalid})


def test_horizon_mismatch_is_rejected():
    service = RecommendationShadowHoldoutGateService(
        minimum_evaluated_horizons=1,
        minimum_passing_horizons=1,
    )

    with pytest.raises(ValueError, match="horizonte distinto"):
        service.evaluate(holdouts={30: _holdout(90)})


def test_non_finite_holdout_metric_is_rejected():
    service = RecommendationShadowHoldoutGateService(
        minimum_evaluated_horizons=1,
        minimum_passing_horizons=1,
    )
    invalid = _holdout(30)
    invalid["relativeMseImprovement"] = float("nan")

    with pytest.raises(ValueError, match="finito"):
        service.evaluate(holdouts={30: invalid})

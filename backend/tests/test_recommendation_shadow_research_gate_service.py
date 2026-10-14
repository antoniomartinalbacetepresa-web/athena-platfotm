import pytest

from app.services.recommendation_shadow_research_gate_service import (
    RecommendationShadowResearchGateService,
)


def _horizon(
    *,
    win_rate=0.75,
    improvement=0.10,
    sign_accuracy=0.55,
    fold_count=4,
    blocked=0,
):
    return {
        "status": "shadow_walk_forward_evaluated",
        "foldCount": fold_count,
        "evaluatedFoldCount": fold_count - blocked,
        "blockedFoldCount": blocked,
        "summary": {
            "baselineWinRate": win_rate,
            "medianRelativeMseImprovement": improvement,
            "medianSignAccuracy": sign_accuracy,
        },
        "productionEligible": False,
    }


def test_pass_only_advances_candidate_to_next_research_stage():
    service = RecommendationShadowResearchGateService()
    evidence = {
        "productionEligible": False,
        "horizons": {
            "7": _horizon(),
            "30": _horizon(win_rate=0.80, improvement=0.05),
            "90": _horizon(win_rate=0.70, improvement=0.02),
        },
    }

    result = service.evaluate(multi_horizon_evidence=evidence)

    assert result["status"] == "shadow_candidate_may_enter_action_calibration_research"
    assert result["researchStageEligible"] is True
    assert result["passingHorizonCount"] == 3
    assert result["productionEligible"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["policy"]["freshUntouchedHoldoutBeforeProduction"] is True
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["nextResearchStage"] == (
        "action_threshold_calibration_with_fresh_holdout_reserved"
    )


def test_fails_when_apparent_edge_is_not_stable_across_enough_horizons():
    service = RecommendationShadowResearchGateService()
    evidence = {
        "productionEligible": False,
        "horizons": {
            "7": _horizon(),
            "30": _horizon(win_rate=0.50, improvement=-0.02, sign_accuracy=0.48),
            "90": _horizon(win_rate=0.60, improvement=0.01),
        },
    }

    result = service.evaluate(multi_horizon_evidence=evidence)

    assert result["status"] == "shadow_candidate_fails_research_gate"
    assert result["researchStageEligible"] is False
    assert result["passingHorizonCount"] == 1
    assert "insufficient_passing_horizons" in result["globalReasons"]
    assert "insufficient_horizon_pass_ratio" in result["globalReasons"]
    assert result["horizons"]["30"]["passesResearchGate"] is False


def test_distinguishes_missing_evidence_from_negative_evidence():
    service = RecommendationShadowResearchGateService()
    evidence = {
        "productionEligible": False,
        "horizons": {
            "7": _horizon(),
            "30": {"status": "missing_walk_forward_folds", "productionEligible": False},
            "90": {"status": "insufficient_walk_forward_evidence", "productionEligible": False},
        },
    }

    result = service.evaluate(multi_horizon_evidence=evidence)

    assert result["status"] == "insufficient_shadow_research_evidence"
    assert result["evaluatedHorizonCount"] == 1
    assert result["horizons"]["30"]["evaluated"] is False
    assert result["horizons"]["90"]["reasons"] == ["walk_forward_not_evaluated"]


def test_blocks_horizon_with_excessive_purging_even_if_metrics_look_good():
    service = RecommendationShadowResearchGateService(
        minimum_evaluated_horizons=1,
        minimum_passing_horizons=1,
        minimum_horizon_pass_ratio=1.0,
        maximum_blocked_fold_ratio=0.20,
    )
    evidence = {
        "productionEligible": False,
        "horizons": {"30": _horizon(fold_count=4, blocked=1)},
    }

    result = service.evaluate(multi_horizon_evidence=evidence)

    assert result["researchStageEligible"] is False
    assert result["horizons"]["30"]["blockedFoldRatio"] == 0.25
    assert "too_many_blocked_folds" in result["horizons"]["30"]["reasons"]


def test_rejects_any_shadow_evidence_marked_as_production_eligible():
    service = RecommendationShadowResearchGateService()

    with pytest.raises(ValueError, match="productionEligible"):
        service.evaluate(
            multi_horizon_evidence={"productionEligible": True, "horizons": {}}
        )

    with pytest.raises(ValueError, match="productionEligible"):
        service.evaluate(
            multi_horizon_evidence={
                "productionEligible": False,
                "horizons": {"30": {**_horizon(), "productionEligible": True}},
            }
        )


def test_rejects_inconsistent_fold_counts_and_non_finite_metrics():
    service = RecommendationShadowResearchGateService(
        minimum_evaluated_horizons=1,
        minimum_passing_horizons=1,
    )
    inconsistent = _horizon()
    inconsistent["evaluatedFoldCount"] = 3
    inconsistent["blockedFoldCount"] = 0

    with pytest.raises(ValueError, match="inconsistentes"):
        service.evaluate(
            multi_horizon_evidence={
                "productionEligible": False,
                "horizons": {"30": inconsistent},
            }
        )

    non_finite = _horizon()
    non_finite["summary"]["medianRelativeMseImprovement"] = float("nan")
    with pytest.raises(ValueError, match="finito"):
        service.evaluate(
            multi_horizon_evidence={
                "productionEligible": False,
                "horizons": {"30": non_finite},
            }
        )

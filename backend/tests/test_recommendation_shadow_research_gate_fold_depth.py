from app.services.recommendation_shadow_research_gate_service import (
    RecommendationShadowResearchGateService,
)


def test_gate_cannot_delegate_minimum_fold_depth_to_upstream_configuration():
    service = RecommendationShadowResearchGateService(
        minimum_evaluated_horizons=1,
        minimum_passing_horizons=1,
        minimum_evaluated_folds_per_horizon=3,
        minimum_horizon_pass_ratio=1.0,
    )
    evidence = {
        "productionEligible": False,
        "horizons": {
            "30": {
                "status": "shadow_walk_forward_evaluated",
                "foldCount": 2,
                "evaluatedFoldCount": 2,
                "blockedFoldCount": 0,
                "summary": {
                    "baselineWinRate": 1.0,
                    "medianRelativeMseImprovement": 0.50,
                    "medianSignAccuracy": 0.90,
                },
                "productionEligible": False,
            }
        },
    }

    result = service.evaluate(multi_horizon_evidence=evidence)

    assert result["researchStageEligible"] is False
    assert result["horizons"]["30"]["passesResearchGate"] is False
    assert result["horizons"]["30"]["reasons"] == [
        "insufficient_evaluated_folds_for_research_gate"
    ]
    assert result["thresholds"]["minimumEvaluatedFoldsPerHorizon"] == 3
    assert result["productionEligible"] is False

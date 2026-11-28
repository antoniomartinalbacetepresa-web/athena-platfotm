from app.services.recommendation_shadow_multi_horizon_service import (
    RecommendationShadowMultiHorizonService,
)


class FakeWalkForwardService:
    def __init__(self, results_by_horizon):
        self.results_by_horizon = dict(results_by_horizon)
        self.calls = []

    def evaluate(self, *, folds, horizon_days):
        self.calls.append({"folds": folds, "horizon_days": horizon_days})
        return self.results_by_horizon[horizon_days]


def _walk_forward(stable):
    return {
        "status": "shadow_walk_forward_evaluated",
        "summary": {"stableDirectionally": stable},
        "productionEligible": False,
    }


def test_multi_horizon_preserves_independent_horizon_results() -> None:
    walk_forward = FakeWalkForwardService(
        {
            7: _walk_forward(True),
            30: _walk_forward(True),
            90: _walk_forward(False),
        }
    )
    service = RecommendationShadowMultiHorizonService(
        walk_forward_service=walk_forward,
        minimum_evaluated_horizons=3,
    )
    folds = {7: ["f7"], 30: ["f30"], 90: ["f90"]}

    result = service.evaluate(folds_by_horizon=folds, horizons=(7, 30, 90))

    assert result["status"] == "shadow_multi_horizon_evaluated"
    assert result["evaluatedHorizonCount"] == 3
    assert result["stableHorizonCount"] == 2
    assert result["coverageRatio"] == 1.0
    assert result["stabilityRatioAcrossEvaluatedHorizons"] == 2 / 3
    assert result["productionEligible"] is False
    assert result["policy"]["actions"] == "not_assigned"
    assert [call["horizon_days"] for call in walk_forward.calls] == [7, 30, 90]


def test_multi_horizon_missing_folds_are_not_counted_as_success() -> None:
    walk_forward = FakeWalkForwardService(
        {
            7: _walk_forward(True),
            30: _walk_forward(True),
        }
    )
    service = RecommendationShadowMultiHorizonService(
        walk_forward_service=walk_forward,
        minimum_evaluated_horizons=3,
    )

    result = service.evaluate(
        folds_by_horizon={7: ["f7"], 30: ["f30"]},
        horizons=(7, 30, 90),
    )

    assert result["status"] == "insufficient_multi_horizon_evidence"
    assert result["evaluatedHorizonCount"] == 2
    assert result["horizons"]["90"]["status"] == "missing_walk_forward_folds"
    assert result["coverageRatio"] == 2 / 3
    assert result["productionEligible"] is False


def test_multi_horizon_blocked_walk_forward_is_not_evaluated() -> None:
    walk_forward = FakeWalkForwardService(
        {
            7: _walk_forward(True),
            30: {
                "status": "insufficient_walk_forward_evidence",
                "productionEligible": False,
            },
        }
    )
    service = RecommendationShadowMultiHorizonService(
        walk_forward_service=walk_forward,
        minimum_evaluated_horizons=2,
    )

    result = service.evaluate(
        folds_by_horizon={7: ["f7"], 30: ["f30"]},
        horizons=(7, 30),
    )

    assert result["status"] == "insufficient_multi_horizon_evidence"
    assert result["evaluatedHorizonCount"] == 1
    assert result["stableHorizonCount"] == 1


def test_multi_horizon_rejects_duplicate_or_invalid_horizons() -> None:
    service = RecommendationShadowMultiHorizonService(
        walk_forward_service=FakeWalkForwardService({}),
    )

    for horizons in ((7, 7), (7, 0)):
        try:
            service.evaluate(folds_by_horizon={}, horizons=horizons)
        except ValueError:
            pass
        else:
            raise AssertionError("Se esperaba rechazo de horizontes inválidos.")

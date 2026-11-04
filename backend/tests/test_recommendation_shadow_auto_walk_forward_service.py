from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_auto_walk_forward_service import (
    RecommendationShadowAutoWalkForwardService,
)


class FakePlanService:
    def __init__(self, fold_counts):
        self.fold_counts = fold_counts
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        horizon = kwargs["horizon_days"]
        folds = [
            {
                "train_end": datetime(2024, 1, index + 1, tzinfo=timezone.utc),
                "validation_end": datetime(2024, 2, index + 1, tzinfo=timezone.utc),
                "as_of": datetime(2024, 3, index + 1, tzinfo=timezone.utc),
            }
            for index in range(self.fold_counts.get(horizon, 0))
        ]
        return {
            "status": "shadow_walk_forward_plan_ready" if folds else "insufficient",
            "horizonDays": horizon,
            "readyFoldCount": len(folds),
            "folds": folds,
            "diagnostics": [],
            "productionEligible": False,
        }


class FakeMultiHorizonService:
    def __init__(self):
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_multi_horizon_evaluated",
            "requestedHorizons": list(kwargs["horizons"]),
            "productionEligible": False,
        }


def test_automatically_passes_only_horizons_with_enough_purged_folds():
    plan = FakePlanService({7: 3, 30: 2, 90: 4})
    multi = FakeMultiHorizonService()
    service = RecommendationShadowAutoWalkForwardService(
        plan_service=plan,
        multi_horizon_service=multi,
        minimum_folds_per_horizon=3,
    )

    result = service.evaluate(
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
        horizons=(7, 30, 90),
    )

    assert result["plannedHorizonCount"] == 2
    assert set(multi.calls[0]["folds_by_horizon"]) == {7, 90}
    assert len(multi.calls[0]["folds_by_horizon"][7]) == 3
    assert len(multi.calls[0]["folds_by_horizon"][90]) == 4
    assert multi.calls[0]["horizons"] == (7, 30, 90)
    assert all(call["require_benchmark"] is True for call in plan.calls)
    assert all("folds" not in public_plan for public_plan in result["plans"].values())
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False


def test_missing_horizon_evidence_is_not_silently_imputed():
    plan = FakePlanService({7: 1, 30: 0})
    multi = FakeMultiHorizonService()
    service = RecommendationShadowAutoWalkForwardService(
        plan_service=plan,
        multi_horizon_service=multi,
        minimum_folds_per_horizon=3,
    )

    result = service.evaluate(
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
        horizons=(7, 30),
    )

    assert result["plannedHorizonCount"] == 0
    assert multi.calls[0]["folds_by_horizon"] == {}
    assert result["plans"]["7"]["readyFoldCount"] == 1
    assert result["plans"]["30"]["readyFoldCount"] == 0


def test_requires_timezone_aware_cutoff():
    service = RecommendationShadowAutoWalkForwardService(
        plan_service=FakePlanService({}),
        multi_horizon_service=FakeMultiHorizonService(),
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(as_of=datetime(2025, 1, 1), horizons=(30,))


def test_rejects_duplicate_or_non_positive_horizons():
    service = RecommendationShadowAutoWalkForwardService(
        plan_service=FakePlanService({}),
        multi_horizon_service=FakeMultiHorizonService(),
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="repetirse"):
        service.evaluate(as_of=cutoff, horizons=(30, 30))
    with pytest.raises(ValueError, match="positivos"):
        service.evaluate(as_of=cutoff, horizons=(0, 30))


def test_minimum_folds_per_horizon_cannot_drop_below_walk_forward_requirement():
    with pytest.raises(ValueError, match="al menos 2"):
        RecommendationShadowAutoWalkForwardService(minimum_folds_per_horizon=1)

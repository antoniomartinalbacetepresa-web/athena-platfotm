from app.services.recommendation_shadow_linear_candidate_service import (
    RecommendationShadowLinearCandidateService,
)


class FakeSplitService:
    def __init__(self, split):
        self.split = split
        self.calls = []

    def build(self, *, require_benchmark=True, **kwargs):
        self.calls.append({"require_benchmark": require_benchmark, **kwargs})
        return self.split


def _row(value, target):
    return {
        "features": {
            "technicalScore": float(value),
            "riskScore": None,
            "return20d": None,
            "return60d": None,
            "annualizedVolatility": None,
            "maxDrawdown60d": None,
            "fundamentalCoverageRatio": None,
            "revenueGrowth": None,
            "netMargin": None,
            "liabilitiesToAssets": None,
            "reportedAnnualPe": None,
        },
        "target": {
            "realizedReturn": float(target) + 0.02,
            "benchmarkReturn": 0.02,
            "excessReturn": float(target),
        },
    }


def _split():
    return {
        "featureSchemaVersion": "shadow-evidence-v1",
        "horizonDays": 30,
        "counts": {"train": 6, "validation": 3, "test": 3, "purged": 0},
        "train": [_row(x, 0.01 * x) for x in range(1, 7)],
        "validation": [_row(x, 0.01 * x) for x in range(7, 10)],
        "test": [_row(x, 0.01 * x) for x in range(10, 13)],
    }


def test_linear_candidate_selects_on_validation_and_evaluates_test() -> None:
    split_service = FakeSplitService(_split())
    service = RecommendationShadowLinearCandidateService(
        split_service=split_service,
        ridge_lambdas=(0.1, 1.0, 10.0),
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )

    result = service.evaluate(as_of="unused", train_end="unused", validation_end="unused")

    assert result["status"] == "shadow_linear_candidate_evaluated"
    assert result["selectedFeatures"] == ["technicalScore"]
    assert result["selection"]["criterion"] == "minimum_validation_mse"
    assert len(result["selection"]["candidates"]) == 3
    assert result["beatsZeroBaselineOnMse"] is True
    assert result["test"]["mse"] < result["zeroExcessReturnBaseline"]["mse"]
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"]["actions"] == "not_assigned"
    assert split_service.calls[0]["require_benchmark"] is True


def test_linear_candidate_blocks_when_any_partition_is_too_small() -> None:
    split = _split()
    split["validation"] = split["validation"][:1]
    split["counts"]["validation"] = 1
    service = RecommendationShadowLinearCandidateService(
        split_service=FakeSplitService(split),
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )

    result = service.evaluate()

    assert result["status"] == "insufficient_shadow_calibration_data"
    assert result["productionEligible"] is False
    assert result["reasons"][0]["partition"] == "validation"


def test_linear_candidate_uses_only_train_to_define_feature_schema() -> None:
    split = _split()
    for row in split["validation"] + split["test"]:
        row["features"]["reportedAnnualPe"] = 20.0
    service = RecommendationShadowLinearCandidateService(
        split_service=FakeSplitService(split),
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )

    result = service.evaluate()

    assert "reportedAnnualPe" not in result["selectedFeatures"]
    assert result["preprocessing"]["imputation"] == "train_median_only"


def test_linear_candidate_rejects_non_finite_excess_target() -> None:
    split = _split()
    split["test"][0]["target"]["excessReturn"] = float("nan")
    service = RecommendationShadowLinearCandidateService(
        split_service=FakeSplitService(split),
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )

    try:
        service.evaluate()
    except ValueError as exc:
        assert "excessReturn no finito" in str(exc)
    else:
        raise AssertionError("Se esperaba un cierre seguro ante un target no finito.")

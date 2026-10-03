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


class ForbiddenSplitService:
    def build(self, **kwargs):
        raise AssertionError("evaluate_frozen_split no debe reconstruir persistencia.")


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
        "featureSchemaVersion": "shadow-evidence-v2",
        "horizonDays": 30,
        "counts": {"train": 6, "validation": 3, "test": 3, "purged": 0},
        "train": [_row(x, 0.01 * x) for x in range(1, 7)],
        "validation": [_row(x, 0.01 * x) for x in range(7, 10)],
        "test": [_row(x, 0.01 * x) for x in range(10, 13)],
    }


def _service(split_service):
    return RecommendationShadowLinearCandidateService(
        split_service=split_service,
        ridge_lambdas=(0.1, 1.0, 10.0),
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )


def test_linear_candidate_selects_on_validation_and_evaluates_test() -> None:
    split_service = FakeSplitService(_split())
    service = _service(split_service)

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


def test_linear_candidate_evaluates_frozen_split_without_second_read() -> None:
    frozen_split = _split()
    service = _service(ForbiddenSplitService())

    result = service.evaluate_frozen_split(split=frozen_split)

    assert result["status"] == "shadow_linear_candidate_evaluated"
    assert result["featureSchemaVersion"] == "shadow-evidence-v2"
    assert result["horizonDays"] == 30
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False


def test_linear_candidate_rejects_inconsistent_frozen_split_counts() -> None:
    frozen_split = _split()
    frozen_split["counts"]["test"] = 99
    service = _service(ForbiddenSplitService())

    try:
        service.evaluate_frozen_split(split=frozen_split)
    except ValueError as exc:
        assert "no coincide" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de un split congelado inconsistente.")


def test_linear_candidate_blocks_when_any_partition_is_too_small() -> None:
    split = _split()
    split["validation"] = split["validation"][:1]
    split["counts"]["validation"] = 1
    service = _service(FakeSplitService(split))

    result = service.evaluate()

    assert result["status"] == "insufficient_shadow_calibration_data"
    assert result["productionEligible"] is False
    assert result["reasons"][0]["partition"] == "validation"


def test_linear_candidate_uses_only_train_to_define_feature_schema() -> None:
    split = _split()
    for row in split["validation"] + split["test"]:
        row["features"]["reportedAnnualPe"] = 20.0
    service = _service(FakeSplitService(split))

    result = service.evaluate()

    assert "reportedAnnualPe" not in result["selectedFeatures"]
    assert result["preprocessing"]["imputation"] == "train_median_only"


def test_linear_candidate_rejects_non_finite_excess_target() -> None:
    split = _split()
    split["test"][0]["target"]["excessReturn"] = float("nan")
    service = _service(FakeSplitService(split))

    try:
        service.evaluate()
    except ValueError as exc:
        assert "excessReturn no finito" in str(exc)
    else:
        raise AssertionError("Se esperaba un cierre seguro ante un target no finito.")


def test_linear_candidate_rejects_boolean_excess_target() -> None:
    split = _split()
    split["test"][0]["target"]["excessReturn"] = True
    service = _service(FakeSplitService(split))

    try:
        service.evaluate_frozen_split(split=split)
    except ValueError as exc:
        assert "excessReturn no finito" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de bool como target numérico.")

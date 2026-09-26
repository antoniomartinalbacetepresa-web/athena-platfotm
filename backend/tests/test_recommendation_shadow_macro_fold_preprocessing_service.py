import math

import pytest

from app.services.recommendation_shadow_macro_fold_preprocessing_service import (
    RecommendationShadowMacroFoldPreprocessingService,
)


def _row(snapshot_id: str, values: dict[str, object]) -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "dataCutoffAt": "2026-01-01T00:00:00+00:00",
        "macroResearchFeatures": [
            {"key": key, "value": value}
            for key, value in values.items()
        ],
        "target": {"excessReturn": 999999.0},
    }


def test_fit_parameters_are_train_only_and_extreme_test_values_do_not_change_them():
    service = RecommendationShadowMacroFoldPreprocessingService()
    train = [
        _row("t1", {"macro.cpi|US|pct": 1.0}),
        _row("t2", {"macro.cpi|US|pct": 3.0}),
    ]
    validation = [_row("v1", {"macro.cpi|US|pct": 1000.0})]
    test = [_row("x1", {"macro.cpi|US|pct": 1_000_000.0})]

    result = service.fit_transform(
        train_rows=train,
        validation_rows=validation,
        test_rows=test,
    )

    assert result["status"] == "shadow_macro_fold_preprocessing_fitted"
    params = result["fitParameters"]["macro.cpi|US|pct"]
    assert params == {"median": 2.0, "mean": 2.0, "populationStd": 1.0}
    assert result["partitions"]["train"][0]["values"]["macro.cpi|US|pct"] == -1.0
    assert result["partitions"]["train"][1]["values"]["macro.cpi|US|pct"] == 1.0
    assert result["productionEligible"] is False
    assert result["advisoryStatus"] == "no_advice"


def test_validation_and_test_only_features_are_ignored():
    service = RecommendationShadowMacroFoldPreprocessingService()
    result = service.fit_transform(
        train_rows=[
            _row("t1", {"macro.cpi|US|pct": 1.0}),
            _row("t2", {"macro.cpi|US|pct": 3.0}),
        ],
        validation_rows=[
            _row(
                "v1",
                {
                    "macro.cpi|US|pct": 2.0,
                    "macro.future|US|idx": 999.0,
                },
            )
        ],
        test_rows=[_row("x1", {"macro.future|US|idx": -999.0})],
    )

    assert result["selectedFeatures"] == ["macro.cpi|US|pct"]
    assert "macro.future|US|idx" not in result["fitParameters"]
    assert result["partitions"]["validation"][0]["values"] == {
        "macro.cpi|US|pct": 0.0
    }
    # Missing train-known CPI in test is imputed with the train median.
    assert result["partitions"]["test"][0]["values"] == {
        "macro.cpi|US|pct": 0.0
    }


def test_missing_values_are_imputed_only_with_train_median():
    service = RecommendationShadowMacroFoldPreprocessingService()
    result = service.fit_transform(
        train_rows=[
            _row("t1", {"macro.cpi|US|pct": 1.0}),
            _row("t2", {"macro.cpi|US|pct": 3.0}),
            _row("t3", {}),
        ],
        validation_rows=[_row("v1", {})],
        test_rows=[_row("x1", {})],
    )

    params = result["fitParameters"]["macro.cpi|US|pct"]
    assert params["median"] == 2.0
    assert params["mean"] == 2.0
    assert math.isclose(params["populationStd"], math.sqrt(2.0 / 3.0))
    assert result["partitions"]["validation"][0]["values"]["macro.cpi|US|pct"] == 0.0
    assert result["partitions"]["test"][0]["values"]["macro.cpi|US|pct"] == 0.0


@pytest.mark.parametrize("bad_value", [True, float("nan"), float("inf"), float("-inf")])
def test_non_finite_or_boolean_macro_values_fail_closed(bad_value):
    service = RecommendationShadowMacroFoldPreprocessingService()
    with pytest.raises(ValueError, match="no finita"):
        service.fit_transform(
            train_rows=[
                _row("t1", {"macro.cpi|US|pct": 1.0}),
                _row("t2", {"macro.cpi|US|pct": bad_value}),
            ],
            validation_rows=[],
            test_rows=[],
        )


def test_constant_train_features_block_instead_of_using_future_variation():
    service = RecommendationShadowMacroFoldPreprocessingService()
    result = service.fit_transform(
        train_rows=[
            _row("t1", {"macro.cpi|US|pct": 2.0}),
            _row("t2", {"macro.cpi|US|pct": 2.0}),
        ],
        validation_rows=[_row("v1", {"macro.cpi|US|pct": 3.0})],
        test_rows=[_row("x1", {"macro.cpi|US|pct": 4.0})],
    )

    assert result["status"] == "insufficient_macro_fold_preprocessing_data"
    assert result["reason"] == "all_train_macro_features_constant"
    assert result["selectedFeatures"] == []
    assert result["productionEligible"] is False

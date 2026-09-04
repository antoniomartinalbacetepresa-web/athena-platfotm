from copy import deepcopy

from app.services.recommendation_shadow_macro_research_feature_service import (
    RecommendationShadowMacroResearchFeatureService,
)


CUT = "2026-01-01T20:00:00+00:00"


def _observation(**overrides):
    value = {
        "metric": "macro.cpi.all_items",
        "entity": "US",
        "value": 312.4,
        "unit": "index",
        "source": "fred_alfred",
        "observedAt": "2025-11-01T00:00:00+00:00",
        "availableAt": "2025-12-10T13:30:00+00:00",
        "retrievedAt": "2026-01-01T19:00:00+00:00",
        "sourceUrl": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "qualityScore": 95.0,
        "confidence": 94.0,
    }
    value.update(overrides)
    return value


def _dataset(observations=None):
    return {
        "status": "shadow_calibration_dataset",
        "featureSchemaVersion": "shadow-evidence-v2",
        "asOf": "2026-01-10T20:00:00+00:00",
        "horizonDays": 7,
        "requireBenchmark": True,
        "rowCount": 1,
        "rows": [
            {
                "snapshotId": 1,
                "instrumentId": 7,
                "symbol": "AAPL",
                "dataCutoffAt": CUT,
                "target": {
                    "realizedReturn": 0.10,
                    "benchmarkReturn": 0.03,
                    "excessReturn": 0.07,
                },
                "features": {"technicalScore": 61.0},
                "macroObservations": observations
                if observations is not None
                else [_observation()],
            }
        ],
        "advisoryStatus": "no_advice",
    }


def test_build_emits_raw_deterministic_macro_features_with_full_provenance() -> None:
    result = RecommendationShadowMacroResearchFeatureService().build(
        calibration_dataset=_dataset()
    )

    assert result["status"] == "shadow_macro_research_dataset"
    assert result["datasetSchemaVersion"] == "shadow-macro-research-v1"
    assert result["sourceFeatureSchemaVersion"] == "shadow-evidence-v2"
    assert result["rowCount"] == 1
    feature = result["rows"][0]["macroResearchFeatures"][0]
    assert feature == {
        "key": "macro.cpi.all_items|US|index",
        "metric": "macro.cpi.all_items",
        "entity": "US",
        "unit": "index",
        "value": 312.4,
        "source": "fred_alfred",
        "observedAt": "2025-11-01T00:00:00+00:00",
        "availableAt": "2025-12-10T13:30:00+00:00",
        "retrievedAt": "2026-01-01T19:00:00+00:00",
        "sourceUrl": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "qualityScore": 95.0,
        "confidence": 94.0,
        "transformation": "raw_frozen_value",
    }
    assert result["advisoryStatus"] == "no_advice"
    assert result["policy"]["normalization"] == "not_fit_in_this_stage"
    assert result["policy"]["direction"] == "not_assigned"
    assert result["policy"]["featureWeights"] == "not_assigned"
    assert result["policy"]["thresholds"] == "not_assigned"
    assert result["policy"]["candidateInfluence"] == "disabled"
    assert "action" not in feature
    assert "weight" not in feature
    assert "direction" not in feature
    assert "score" not in feature


def test_build_deduplicates_exact_macro_feature_identity_deterministically() -> None:
    observation = _observation()
    other = _observation(
        metric="macro.policy_rate",
        value=4.25,
        unit="percent",
        sourceUrl="https://fred.stlouisfed.org/series/FEDFUNDS",
    )
    result = RecommendationShadowMacroResearchFeatureService().build(
        calibration_dataset=_dataset([other, observation, deepcopy(observation)])
    )

    assert result["rowCount"] == 1
    assert [
        feature["key"] for feature in result["rows"][0]["macroResearchFeatures"]
    ] == [
        "macro.cpi.all_items|US|index",
        "macro.policy_rate|US|percent",
    ]


def test_build_rejects_conflicting_duplicate_macro_feature_identity() -> None:
    observation = _observation()
    conflicting = _observation(value=313.0)

    result = RecommendationShadowMacroResearchFeatureService().build(
        calibration_dataset=_dataset([observation, conflicting])
    )

    assert result["rowCount"] == 0
    assert result["rejectedInvalidMacroCount"] == 1


def test_build_rejects_non_finite_and_boolean_macro_values() -> None:
    service = RecommendationShadowMacroResearchFeatureService()

    for invalid in (float("nan"), float("inf"), float("-inf"), True):
        result = service.build(
            calibration_dataset=_dataset([_observation(value=invalid)])
        )
        assert result["rowCount"] == 0
        assert result["rejectedInvalidMacroCount"] == 1


def test_build_rejects_macro_timestamps_after_snapshot_cutoff() -> None:
    service = RecommendationShadowMacroResearchFeatureService()

    for field in ("availableAt", "retrievedAt"):
        result = service.build(
            calibration_dataset=_dataset(
                [_observation(**{field: "2026-01-01T20:00:01+00:00"})]
            )
        )
        assert result["rowCount"] == 0
        assert result["rejectedInvalidMacroCount"] == 1


def test_build_rejects_observation_after_public_availability() -> None:
    result = RecommendationShadowMacroResearchFeatureService().build(
        calibration_dataset=_dataset(
            [_observation(observedAt="2025-12-11T00:00:00+00:00")]
        )
    )

    assert result["rowCount"] == 0
    assert result["rejectedInvalidMacroCount"] == 1


def test_build_does_not_mutate_source_calibration_dataset() -> None:
    source = _dataset()
    original = deepcopy(source)

    RecommendationShadowMacroResearchFeatureService().build(
        calibration_dataset=source
    )

    assert source == original

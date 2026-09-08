from __future__ import annotations

import hashlib
import json

import pytest

from app.services.recommendation_research_forecast_error_oos_summary_integrity_service import (
    RecommendationResearchForecastErrorOosSummaryIntegrityService,
)


def _hash(payload: object) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _artifact() -> dict[str, object]:
    rows = [
        {
            "errorHash": "a" * 64,
            "specificationHash": "b" * 64,
            "outcomeHash": "c" * 64,
            "cycleHash": "d" * 64,
            "instrumentId": "instrument-a",
            "symbol": "AAA",
            "periodStart": "2026-06-01T00:00:00+00:00",
            "periodEnd": "2026-07-01T00:00:00+00:00",
            "horizonSeconds": 2592000,
            "expectedValue": 0.10,
            "realizedValue": 0.12,
            "signedError": 0.02,
            "absoluteError": 0.02,
            "squaredError": 0.0004,
            "method": "athena-v1",
        },
        {
            "errorHash": "e" * 64,
            "specificationHash": "f" * 64,
            "outcomeHash": "1" * 64,
            "cycleHash": "2" * 64,
            "instrumentId": "instrument-b",
            "symbol": "BBB",
            "periodStart": "2026-07-02T00:00:00+00:00",
            "periodEnd": "2026-08-01T00:00:00+00:00",
            "horizonSeconds": 2592000,
            "expectedValue": 0.08,
            "realizedValue": 0.04,
            "signedError": -0.04,
            "absoluteError": 0.04,
            "squaredError": 0.0016,
            "method": "athena-v1",
        },
    ]
    core: dict[str, object] = {
        "artifactVersion": "research-forecast-error-oos-summary-v1",
        "summaryId": "athena-v1-30d",
        "asOf": "2026-09-01T00:00:00+00:00",
        "method": "athena-v1",
        "horizonSeconds": 2592000,
        "observationCount": 2,
        "distinctInstrumentCount": 2,
        "maximumObservationsPerInstrument": 1,
        "overlappingPeriodPairCount": 0,
        "metrics": {
            "meanSignedError": -0.01,
            "meanAbsoluteError": 0.03,
            "rootMeanSquaredError": (0.001 ** 0.5),
            "medianAbsoluteError": 0.03,
        },
        "errorHashes": ["a" * 64, "e" * 64],
        "rows": rows,
    }
    return {
        "module": "research_forecast_error_oos_summary",
        **core,
        "summaryHash": _hash(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "recommendationCandidateReady": False,
        "productionLearningEligible": False,
        "learningResearchDatasetReady": True,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "lookAhead": "only_persisted_errors_and_specifications_created_at_or_before_summary_as_of",
            "comparability": "single_explicit_method_and_exact_horizon_required",
            "periodOverlap": "reported_not_silently_treated_as_independent",
            "statisticalIndependence": "not_claimed",
            "skillClaim": "forbidden_descriptive_errors_do_not_establish_skill",
            "thresholdCalibration": "not_calibrated",
            "recommendationReadiness": "not_established",
            "learningUse": "research_only_no_automatic_model_update",
            "causalClaim": "forbidden",
        },
    }


def _recompute_hash(artifact: dict[str, object]) -> None:
    core_keys = (
        "artifactVersion",
        "summaryId",
        "asOf",
        "method",
        "horizonSeconds",
        "observationCount",
        "distinctInstrumentCount",
        "maximumObservationsPerInstrument",
        "overlappingPeriodPairCount",
        "metrics",
        "errorHashes",
        "rows",
    )
    artifact["summaryHash"] = _hash({key: artifact[key] for key in core_keys})


def test_integrity_validator_accepts_consistent_summary() -> None:
    validated = RecommendationResearchForecastErrorOosSummaryIntegrityService().validate_artifact(
        _artifact()
    )
    assert validated["advisoryStatus"] == "no_advice"
    assert validated["productionEligible"] is False
    assert validated["isWeightingReady"] is False
    assert validated["recommendationCandidateReady"] is False
    assert validated["productionLearningEligible"] is False
    assert validated["policy"]["automaticTrading"] is False


def test_integrity_validator_rejects_rehashed_semantic_metric_tampering() -> None:
    artifact = _artifact()
    artifact["metrics"]["meanAbsoluteError"] = 0.0  # type: ignore[index]
    _recompute_hash(artifact)

    with pytest.raises(ValueError, match="meanAbsoluteError no reconcilia"):
        RecommendationResearchForecastErrorOosSummaryIntegrityService().validate_artifact(artifact)


def test_integrity_validator_rejects_rehashed_counter_tampering() -> None:
    artifact = _artifact()
    artifact["observationCount"] = 3
    _recompute_hash(artifact)

    with pytest.raises(ValueError, match="observationCount"):
        RecommendationResearchForecastErrorOosSummaryIntegrityService().validate_artifact(artifact)


def test_integrity_validator_rejects_rehashed_error_arithmetic_tampering() -> None:
    artifact = _artifact()
    artifact["rows"][0]["signedError"] = 0.03  # type: ignore[index]
    artifact["rows"][0]["absoluteError"] = 0.03  # type: ignore[index]
    artifact["rows"][0]["squaredError"] = 0.0009  # type: ignore[index]
    artifact["metrics"] = {
        "meanSignedError": -0.005,
        "meanAbsoluteError": 0.035,
        "rootMeanSquaredError": ((0.0009 + 0.0016) / 2) ** 0.5,
        "medianAbsoluteError": 0.035,
    }
    _recompute_hash(artifact)

    with pytest.raises(ValueError, match="signedError no reconcilia"):
        RecommendationResearchForecastErrorOosSummaryIntegrityService().validate_artifact(artifact)

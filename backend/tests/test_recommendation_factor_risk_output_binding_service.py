from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_factor_risk_output_binding_service import (
    RecommendationFactorRiskOutputBindingService,
)
from app.services.recommendation_factor_risk_service import FactorRiskPositionInput


UTC = timezone.utc
AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def expected_position(*, factors: dict[str, float] | None = None) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=1,
        symbol="AAA",
        weight=0.75,
        exposure_available_at=AS_OF,
        source="sealed_market_beta+sealed_portfolio_valuation_fx",
        source_ref="market:" + "a" * 64 + ";usd_fx:valuation:" + "b" * 64,
        factors=factors or {"market": 1.2, "usd_fx": -1.0},
    )


def payload(*, factors: dict[str, float] | None = None) -> dict[str, object]:
    values = factors or {"market": 1.2, "usd_fx": -1.0}
    return {
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "weight": 0.75,
                "exposureAvailableAt": AS_OF.isoformat(),
                "source": "sealed_market_beta+sealed_portfolio_valuation_fx",
                "sourceRef": "market:" + "a" * 64 + ";usd_fx:valuation:" + "b" * 64,
                "factors": dict(values),
            }
        ],
        "weightedExposures": {
            "market": 0.9,
            "usd_fx": -0.75,
            "size": 0.0,
        },
        "factorCoverageWeights": {
            "market": 0.75,
            "usd_fx": 0.75,
            "size": 0.0,
        },
    }


def test_output_binding_accepts_exact_derived_evidence_and_zero_missing_coverage() -> None:
    RecommendationFactorRiskOutputBindingService().validate(
        payload=payload(),
        expected_positions=(expected_position(),),
    )


def test_output_binding_rejects_changed_canonical_weight() -> None:
    body = payload()
    body["positions"][0]["weight"] = 0.74  # type: ignore[index]
    with pytest.raises(ValueError, match="weight"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_changed_sealed_factor_value() -> None:
    body = payload()
    body["positions"][0]["factors"]["market"] = 9.0  # type: ignore[index]
    with pytest.raises(ValueError, match="factors.market"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_injected_sealed_factor_without_evidence() -> None:
    body = payload()
    body["positions"][0]["factors"]["rates"] = 0.8  # type: ignore[index]
    body["weightedExposures"]["rates"] = 0.6  # type: ignore[index]
    body["factorCoverageWeights"]["rates"] = 0.75  # type: ignore[index]
    with pytest.raises(ValueError, match="añadió u omitió factores"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_omitted_sealed_factor() -> None:
    body = payload()
    del body["positions"][0]["factors"]["usd_fx"]  # type: ignore[index]
    with pytest.raises(ValueError, match="añadió u omitió factores"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_tampered_provenance() -> None:
    body = payload()
    body["positions"][0]["sourceRef"] = "caller:forged"  # type: ignore[index]
    with pytest.raises(ValueError, match="sourceRef"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_non_reconciling_aggregate() -> None:
    body = payload()
    body["weightedExposures"]["market"] = 0.89  # type: ignore[index]
    with pytest.raises(ValueError, match="weightedExposures.market"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )


def test_output_binding_rejects_nonzero_missing_factor_aggregate() -> None:
    body = payload()
    body["weightedExposures"]["size"] = 0.25  # type: ignore[index]
    with pytest.raises(ValueError, match="weightedExposures.size"):
        RecommendationFactorRiskOutputBindingService().validate(
            payload=body,
            expected_positions=(expected_position(),),
        )

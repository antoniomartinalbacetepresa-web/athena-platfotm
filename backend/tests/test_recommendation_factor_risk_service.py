from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


def _position(
    *,
    instrument_id: int,
    symbol: str,
    weight: float,
    factors: dict[str, float],
    available_at: datetime = AVAILABLE_AT,
    source: str = "pit_factor_store",
    source_ref: str | None = None,
) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        weight=weight,
        exposure_available_at=available_at,
        source=source,
        source_ref=source_ref or f"factor:{instrument_id}:2025-12-31",
        factors=factors,
    )


def test_factor_risk_preserves_pit_provenance_and_reports_coverage() -> None:
    result = RecommendationFactorRiskService().evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.60,
                factors={"market": 1.2, "quality": 0.5, "usd_fx": 0.1},
            ),
            _position(
                instrument_id=2,
                symbol="BBB",
                weight=0.30,
                factors={"market": 0.8, "quality": -0.2},
            ),
        ),
    )

    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["investedWeight"] == pytest.approx(0.9)
    assert payload["cashWeight"] == pytest.approx(0.1)
    assert payload["weightedExposures"]["market"] == pytest.approx(0.96)
    assert payload["weightedExposures"]["quality"] == pytest.approx(0.24)
    assert payload["factorCoverageWeights"]["market"] == pytest.approx(0.9)
    assert payload["factorCoverageWeights"]["quality"] == pytest.approx(0.9)
    assert payload["factorCoverageWeights"]["usd_fx"] == pytest.approx(0.6)
    assert "market" in payload["fullyCoveredFactors"]
    assert "quality" in payload["fullyCoveredFactors"]
    assert "usd_fx" not in payload["fullyCoveredFactors"]
    assert payload["dominantFactor"] == "market"
    assert payload["positions"][0]["sourceRef"] == "factor:1:2025-12-31"
    assert payload["positions"][0]["exposureAvailableAt"] == AVAILABLE_AT.isoformat()
    assert payload["policy"]["missingFactorCoverage"] == "reported_explicitly_never_imputed_as_zero"
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False


def test_factor_risk_does_not_select_dominant_factor_from_partial_coverage() -> None:
    result = RecommendationFactorRiskService().evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.50,
                factors={"market": 0.2, "usd_fx": 5.0},
            ),
            _position(
                instrument_id=2,
                symbol="BBB",
                weight=0.50,
                factors={"market": 0.3},
            ),
        ),
    )

    payload = result.to_api_dict()
    assert payload["weightedExposures"]["usd_fx"] == pytest.approx(2.5)
    assert payload["factorCoverageWeights"]["usd_fx"] == pytest.approx(0.5)
    assert "usd_fx" not in payload["fullyCoveredFactors"]
    assert payload["dominantFactor"] == "market"
    assert payload["grossFactorExposure"] == pytest.approx(0.25)


def test_factor_risk_rejects_lookahead_and_naive_timestamps() -> None:
    service = RecommendationFactorRiskService()

    with pytest.raises(ValueError, match="look-ahead"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                    available_at=AS_OF + timedelta(microseconds=1),
                ),
            ),
        )

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            as_of=datetime(2026, 1, 1),
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                ),
            ),
        )


def test_factor_risk_rejects_duplicate_identity_and_invalid_portfolio_weight() -> None:
    service = RecommendationFactorRiskService()

    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(instrument_id=1, symbol="AAA", weight=0.5, factors={"market": 1.0}),
                _position(instrument_id=1, symbol="BBB", weight=0.5, factors={"market": 1.0}),
            ),
        )

    with pytest.raises(ValueError, match="suma de weights"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(instrument_id=1, symbol="AAA", weight=0.7, factors={"market": 1.0}),
                _position(instrument_id=2, symbol="BBB", weight=0.4, factors={"market": 1.0}),
            ),
        )


def test_factor_risk_rejects_non_finite_unknown_and_missing_provenance() -> None:
    service = RecommendationFactorRiskService()

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finito"):
            service.evaluate(
                as_of=AS_OF,
                positions=(
                    _position(
                        instrument_id=1,
                        symbol="AAA",
                        weight=1.0,
                        factors={"market": value},
                    ),
                ),
            )

    with pytest.raises(ValueError, match="Factor no soportado"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"magic_alpha": 1.0},
                ),
            ),
        )

    with pytest.raises(ValueError, match="source_ref"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                    source_ref=" ",
                ),
            ),
        )

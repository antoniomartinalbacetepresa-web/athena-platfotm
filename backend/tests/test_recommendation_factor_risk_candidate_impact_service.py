from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_factor_risk_candidate_impact_service import (
    RecommendationFactorRiskCandidateImpactService,
)
from app.services.recommendation_factor_risk_service import FactorRiskPositionInput


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


def _position(
    *,
    instrument_id: int,
    symbol: str,
    weight: float,
    factors: dict[str, float],
    available_at: datetime = AVAILABLE_AT,
) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        weight=weight,
        exposure_available_at=available_at,
        source="pit_factor_store",
        source_ref=f"factor:{instrument_id}:2025-12-31",
        factors=factors,
    )


def test_candidate_impact_compares_only_common_full_coverage() -> None:
    result = RecommendationFactorRiskCandidateImpactService().evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.60,
                factors={"market": 1.0, "value": 0.5, "usd_fx": 0.2},
            ),
        ),
        candidate=_position(
            instrument_id=2,
            symbol="BBB",
            weight=0.20,
            factors={"market": -1.0, "value": 0.5, "usd_fx": 0.2},
        ),
    )

    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["baselineCashWeight"] == pytest.approx(0.4)
    assert payload["postCashWeight"] == pytest.approx(0.2)
    assert payload["comparableFactors"] == ["market", "usd_fx", "value"]
    assert payload["coverageLostFactors"] == []
    assert payload["baselineWeightedExposures"]["market"] == pytest.approx(0.6)
    assert payload["postWeightedExposures"]["market"] == pytest.approx(0.4)
    assert payload["factorExposureDeltas"]["market"] == pytest.approx(-0.2)
    assert payload["factorExposureDeltas"]["value"] == pytest.approx(0.1)
    assert payload["candidate"]["sourceRef"] == "factor:2:2025-12-31"
    assert payload["policy"]["covariance"] == "not_estimated_no_marginal_variance_or_risk_contribution_claim"
    assert payload["policy"]["automaticTrading"] is False


def test_candidate_impact_reports_lost_coverage_instead_of_imputing_zero() -> None:
    result = RecommendationFactorRiskCandidateImpactService().evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.50,
                factors={"market": 1.0, "value": 0.4},
            ),
        ),
        candidate=_position(
            instrument_id=2,
            symbol="BBB",
            weight=0.20,
            factors={"value": -0.2},
        ),
    )

    payload = result.to_api_dict()
    assert payload["comparableFactors"] == ["value"]
    assert payload["coverageLostFactors"] == ["market"]
    assert "market" not in payload["factorExposureDeltas"]
    assert payload["policy"]["missingFactorCoverage"] == "coverage_loss_is_reported_never_imputed_as_zero"


def test_candidate_impact_rejects_hidden_rebalancing_and_zero_weight() -> None:
    service = RecommendationFactorRiskCandidateImpactService()
    current = (
        _position(instrument_id=1, symbol="AAA", weight=0.90, factors={"market": 1.0}),
    )

    with pytest.raises(ValueError, match="efectivo disponible"):
        service.evaluate(
            as_of=AS_OF,
            positions=current,
            candidate=_position(instrument_id=2, symbol="BBB", weight=0.20, factors={"market": 0.5}),
        )

    with pytest.raises(ValueError, match="mayor que cero"):
        service.evaluate(
            as_of=AS_OF,
            positions=current,
            candidate=_position(instrument_id=2, symbol="BBB", weight=0.0, factors={"market": 0.5}),
        )


def test_candidate_impact_preserves_pit_and_identity_safeguards() -> None:
    service = RecommendationFactorRiskCandidateImpactService()
    current = (
        _position(instrument_id=1, symbol="AAA", weight=0.50, factors={"market": 1.0}),
    )

    with pytest.raises(ValueError, match="look-ahead"):
        service.evaluate(
            as_of=AS_OF,
            positions=current,
            candidate=_position(
                instrument_id=2,
                symbol="BBB",
                weight=0.20,
                factors={"market": 0.5},
                available_at=AS_OF + timedelta(microseconds=1),
            ),
        )

    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate(
            as_of=AS_OF,
            positions=current,
            candidate=_position(instrument_id=1, symbol="BBB", weight=0.20, factors={"market": 0.5}),
        )


def test_candidate_impact_refuses_false_comparison_without_common_full_coverage() -> None:
    service = RecommendationFactorRiskCandidateImpactService()

    with pytest.raises(ValueError, match="No existen factores"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(instrument_id=1, symbol="AAA", weight=0.50, factors={"market": 1.0}),
            ),
            candidate=_position(
                instrument_id=2,
                symbol="BBB",
                weight=0.20,
                factors={"value": 0.5},
            ),
        )

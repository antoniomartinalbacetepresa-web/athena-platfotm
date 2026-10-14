from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)


AS_OF = datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)
AS_OF_TEXT = AS_OF.isoformat()


@dataclass(frozen=True)
class _Diagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Service:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def evaluate(self, *, symbol: str, as_of: datetime) -> _Diagnostic:
        return _Diagnostic(self.payload)


def _market() -> dict[str, object]:
    return {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 1,
        "asOf": AS_OF_TEXT,
        "observationCount": 80,
        "latestObservedAt": "2026-09-01T20:00:00+00:00",
        "latestRetrievedAt": "2026-09-01T20:10:00+00:00",
        "latestPrice": 100.0,
        "return20d": 0.05,
        "return60d": 0.10,
        "annualizedVolatility": 0.20,
        "maxDrawdown60d": -0.08,
        "technicalScore": 55.0,
        "riskScore": 28.0,
        "sourceProviders": ["yahoo_finance"],
        "productionEligible": False,
    }


def _fundamentals(*, coverage: float = 0.5, net_margin: object = 0.2) -> dict[str, object]:
    return {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 1,
        "entityId": "sec-cik:0000320193",
        "asOf": AS_OF_TEXT,
        "coverageRatio": coverage,
        "revenueGrowth": 0.08,
        "netMargin": net_margin,
        "liabilitiesToAssets": 0.45,
        "meanQualityScore": 0.95,
        "facts": [
            {
                "key": "revenue",
                "metric": "fundamental.us-gaap.revenues",
                "value": 100.0,
                "availableAt": "2026-08-01T00:00:00+00:00",
                "qualityScore": 0.95,
            }
        ],
        "productionEligible": False,
    }


def _valuation() -> dict[str, object]:
    return {
        "status": "valuation_input_missing",
        "symbol": "AAPL",
        "instrumentId": 1,
        "entityId": "sec-cik:0000320193",
        "asOf": AS_OF_TEXT,
        "latestPrice": 100.0,
        "latestPriceObservedAt": "2026-09-01T20:00:00+00:00",
        "latestPriceRetrievedAt": "2026-09-01T20:10:00+00:00",
        "marketSourceProviders": ["yahoo_finance"],
        "annualDilutedEps": None,
        "reportedAnnualPe": None,
        "productionEligible": False,
    }


def _macro() -> dict[str, object]:
    return {
        "status": "no_data",
        "symbol": "AAPL",
        "asOf": AS_OF_TEXT,
        "observationCount": 0,
        "observations": [],
        "productionEligible": False,
    }


def _service(fundamentals: dict[str, object]) -> RecommendationEvidenceGateService:
    return RecommendationEvidenceGateService(
        market_service=_Service(_market()),
        fundamental_service=_Service(fundamentals),
        valuation_service=_Service(_valuation()),
        macro_service=_Service(_macro()),
    )


def test_gate_does_not_use_coverage_percentage_as_readiness_threshold() -> None:
    result = _service(_fundamentals(coverage=0.5)).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    )

    assert result.fundamental_evidence_ready is True
    assert result.core_evidence_ready is True
    assert result.production_eligible is False
    assert result.recommendation_candidate_ready is False
    assert result.calibration_ready is False
    assert result.to_api_dict()["policy"]["fundamentalReadiness"] == (
        "all_consumed_derived_features_present_and_finite_"
        "coverage_ratio_is_diagnostic_only"
    )


def test_gate_fails_closed_when_consumed_fundamental_feature_is_missing() -> None:
    result = _service(_fundamentals(coverage=1.0, net_margin=None)).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    )

    assert result.fundamental_evidence_ready is False
    assert result.data_quality_ready is False
    assert result.core_evidence_ready is False
    assert "fundamental_evidence_not_ready" in result.blockers
    assert "data_quality_contract_incomplete" in result.blockers
    assert result.production_eligible is False
    assert result.recommendation_candidate_ready is False

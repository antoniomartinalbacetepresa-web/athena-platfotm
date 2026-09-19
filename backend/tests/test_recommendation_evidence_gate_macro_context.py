from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)


AS_OF = datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)
AS_OF_TEXT = "2026-09-01T20:30:00+00:00"


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


def _fundamentals() -> dict[str, object]:
    return {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 1,
        "entityId": "sec-cik:0000320193",
        "asOf": AS_OF_TEXT,
        "coverageRatio": 1.0,
        "revenueGrowth": 0.08,
        "netMargin": 0.20,
        "liabilitiesToAssets": 0.45,
        "meanQualityScore": 0.95,
        "facts": [
            {
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
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 1,
        "entityId": "sec-cik:0000320193",
        "asOf": AS_OF_TEXT,
        "latestPrice": 100.0,
        "latestPriceObservedAt": "2026-09-01T20:00:00+00:00",
        "latestPriceRetrievedAt": "2026-09-01T20:10:00+00:00",
        "marketSourceProviders": ["yahoo_finance"],
        "annualDilutedEps": {
            "metric": "fundamental.us-gaap.earningspersharediluted",
            "value": 8.0,
            "availableAt": "2026-08-01T00:00:00+00:00",
            "sourceVersion": "10-K|accession|CY2025",
            "qualityScore": 0.95,
        },
        "reportedAnnualPe": 12.5,
        "productionEligible": False,
    }


def _macro_observation(
    *,
    value: object = 4.2,
    available_at: str = "2026-08-15T12:00:00+00:00",
    retrieved_at: str = "2026-08-15T12:05:00+00:00",
) -> dict[str, object]:
    return {
        "metric": "macro.us.cpi_yoy",
        "entityId": "US",
        "value": value,
        "unit": "percent",
        "sourceId": "fred_alfred",
        "effectiveAt": "2026-07-01T00:00:00+00:00",
        "publishedAt": "2026-08-15T12:00:00+00:00",
        "availableAt": available_at,
        "retrievedAt": retrieved_at,
        "sourceVersion": "vintage:2026-08-15",
        "sourceUrl": "https://fred.stlouisfed.org/",
        "qualityScore": 95.0,
        "confidenceScore": 95.0,
    }


def _macro_ready() -> dict[str, object]:
    return {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "asOf": AS_OF_TEXT,
        "observationCount": 1,
        "observations": [_macro_observation()],
        "productionEligible": False,
    }


def _service(macro_payload: dict[str, object]) -> RecommendationEvidenceGateService:
    return RecommendationEvidenceGateService(
        market_service=_Service(_market()),
        fundamental_service=_Service(_fundamentals()),
        valuation_service=_Service(_valuation()),
        macro_service=_Service(macro_payload),
    )


def test_gate_captures_valid_pit_macro_context_without_assigning_direction_or_weight() -> None:
    payload = _service(_macro_ready()).evaluate(symbol="AAPL", as_of=AS_OF).to_api_dict()

    assert payload["macroContextReady"] is True
    assert payload["macroContextValid"] is True
    assert payload["macro"]["observations"][0]["sourceId"] == "fred_alfred"
    coverage = payload["analysisCoverage"]["marketMacro"]
    assert coverage == {
        "connected": True,
        "influencesCandidate": False,
        "sourceBlock": "macro",
        "status": "diagnostic_ready",
        "evidenceReady": True,
        "capturedForCalibration": True,
        "directionalScoreAssigned": False,
        "thresholdCalibrated": False,
        "productionEligible": False,
    }
    assert payload["policy"]["macro"] == (
        "persisted_pit_context_captured_for_future_out_of_sample_"
        "calibration_no_direction_or_weight_assumed"
    )
    assert payload["calibrationReady"] is False
    assert payload["recommendationCandidateReady"] is False
    assert payload["productionEligible"] is False


def test_gate_allows_absent_macro_context_without_inventing_evidence() -> None:
    macro = {
        "status": "no_data",
        "symbol": "AAPL",
        "asOf": AS_OF_TEXT,
        "observationCount": 0,
        "observations": [],
        "productionEligible": False,
    }

    payload = _service(macro).evaluate(symbol="AAPL", as_of=AS_OF).to_api_dict()

    assert payload["macroContextReady"] is False
    assert payload["macroContextValid"] is True
    assert "macro_context_invalid" not in payload["blockers"]
    assert payload["analysisCoverage"]["marketMacro"] == {
        "connected": False,
        "influencesCandidate": False,
        "status": "infrastructure_available_not_connected_to_candidate",
        "evidenceReady": False,
        "productionEligible": False,
    }
    assert payload["productionEligible"] is False


def test_gate_fails_closed_when_macro_context_claims_ready_with_future_retrieval() -> None:
    macro = _macro_ready()
    macro["observations"] = [
        _macro_observation(retrieved_at="2026-09-02T00:00:00+00:00")
    ]

    payload = _service(macro).evaluate(symbol="AAPL", as_of=AS_OF).to_api_dict()

    assert payload["macroContextReady"] is False
    assert payload["macroContextValid"] is False
    assert "macro_context_invalid" in payload["blockers"]
    assert payload["recommendationCandidateReady"] is False
    assert payload["productionEligible"] is False


def test_gate_fails_closed_on_non_finite_macro_value() -> None:
    macro = _macro_ready()
    macro["observations"] = [_macro_observation(value=float("inf"))]

    payload = _service(macro).evaluate(symbol="AAPL", as_of=AS_OF).to_api_dict()

    assert payload["macroContextReady"] is False
    assert payload["macroContextValid"] is False
    assert "macro_context_invalid" in payload["blockers"]
    assert payload["productionEligible"] is False

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)


AS_OF = datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Diagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Service:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _Diagnostic:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _Diagnostic(self.payload)


def _market_payload(
    *,
    status: str = "diagnostic_ready",
    instrument_id: int = 1,
    production_eligible: bool = False,
    as_of: str = "2026-09-01T20:30:00+00:00",
    source_providers: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "symbol": "AAPL",
        "instrumentId": instrument_id,
        "asOf": as_of,
        "observationCount": 80,
        "productionEligible": production_eligible,
    }
    if source_providers is not None:
        payload["sourceProviders"] = source_providers
    return payload


def _fundamental_payload(
    *,
    status: str = "diagnostic_ready",
    instrument_id: int = 1,
    coverage_ratio: float = 1.0,
    production_eligible: bool = False,
    as_of: str = "2026-09-01T20:30:00+00:00",
) -> dict[str, object]:
    return {
        "status": status,
        "symbol": "AAPL",
        "instrumentId": instrument_id,
        "entityId": "sec-cik:0000320193",
        "asOf": as_of,
        "coverageRatio": coverage_ratio,
        "facts": [
            {
                "key": "revenue",
                "metric": "fundamental.us-gaap.revenues",
                "value": 100.0,
                "availableAt": "2026-08-01T00:00:00+00:00",
            }
        ],
        "productionEligible": production_eligible,
    }


def test_gate_keeps_recommendation_blocked_even_when_core_evidence_is_ready() -> None:
    market = _Service(_market_payload(source_providers=["yahoo_finance"]))
    fundamentals = _Service(_fundamental_payload())
    service = RecommendationEvidenceGateService(
        market_service=market,
        fundamental_service=fundamentals,
    )

    result = service.evaluate(symbol=" aapl ", as_of=AS_OF)

    assert result.status == "core_evidence_ready"
    assert result.symbol == "AAPL"
    assert result.instrument_id == 1
    assert result.core_evidence_ready is True
    assert result.market_evidence_ready is True
    assert result.fundamental_evidence_ready is True
    assert result.identity_consistent is True
    assert result.provenance_contract_ready is True
    assert result.valuation_ready is False
    assert result.calibration_ready is False
    assert result.recommendation_candidate_ready is False
    assert result.production_eligible is False
    assert result.blockers == (
        "valuation_not_ready",
        "calibration_not_validated",
    )
    assert market.calls == [{"symbol": "AAPL", "as_of": AS_OF}]
    assert fundamentals.calls == [{"symbol": "AAPL", "as_of": AS_OF}]


def test_gate_blocks_partial_fundamentals_and_missing_market_provenance() -> None:
    service = RecommendationEvidenceGateService(
        market_service=_Service(_market_payload()),
        fundamental_service=_Service(
            _fundamental_payload(
                status="partial_fundamentals",
                coverage_ratio=0.5,
            )
        ),
    )

    result = service.evaluate(symbol="AAPL", as_of=AS_OF)

    assert result.status == "evidence_incomplete"
    assert result.core_evidence_ready is False
    assert result.fundamental_evidence_ready is False
    assert result.provenance_contract_ready is False
    assert "fundamental_evidence_not_ready" in result.blockers
    assert "provenance_contract_incomplete" in result.blockers
    assert result.production_eligible is False


def test_gate_blocks_instrument_identity_mismatch() -> None:
    service = RecommendationEvidenceGateService(
        market_service=_Service(
            _market_payload(instrument_id=1, source_providers=["yahoo_finance"])
        ),
        fundamental_service=_Service(_fundamental_payload(instrument_id=2)),
    )

    result = service.evaluate(symbol="AAPL", as_of=AS_OF)

    assert result.identity_consistent is False
    assert result.instrument_id is None
    assert result.core_evidence_ready is False
    assert "instrument_identity_mismatch" in result.blockers


def test_gate_fails_closed_if_component_claims_production_eligibility() -> None:
    service = RecommendationEvidenceGateService(
        market_service=_Service(
            _market_payload(
                source_providers=["yahoo_finance"],
                production_eligible=True,
            )
        ),
        fundamental_service=_Service(_fundamental_payload()),
    )

    with pytest.raises(RuntimeError, match="productivo"):
        service.evaluate(symbol="AAPL", as_of=AS_OF)


def test_gate_fails_closed_if_component_uses_different_point_in_time_cutoff() -> None:
    service = RecommendationEvidenceGateService(
        market_service=_Service(
            _market_payload(
                source_providers=["yahoo_finance"],
                as_of="2026-09-01T20:29:59+00:00",
            )
        ),
        fundamental_service=_Service(_fundamental_payload()),
    )

    with pytest.raises(RuntimeError, match="point-in-time distinto"):
        service.evaluate(symbol="AAPL", as_of=AS_OF)


def test_gate_rejects_naive_as_of_before_calling_components() -> None:
    market = _Service(_market_payload(source_providers=["yahoo_finance"]))
    fundamentals = _Service(_fundamental_payload())
    service = RecommendationEvidenceGateService(
        market_service=market,
        fundamental_service=fundamentals,
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=datetime(2026, 9, 1, 20, 30),
        )

    assert market.calls == []
    assert fundamentals.calls == []

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_capture_service import (
    RecommendationShadowCaptureService,
)


AS_OF = datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Diagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Gate:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _Diagnostic:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _Diagnostic(self.payload)


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_snapshot(self, **kwargs: object) -> int:
        self.calls.append(dict(kwargs))
        return 42


def _ready_payload() -> dict[str, object]:
    return {
        "status": "evidence_ready_for_calibration",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "instrumentId": 1,
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "blockers": ["calibration_not_validated"],
        "market": {
            "latestPrice": 200.0,
            "latestObservedAt": (AS_OF - timedelta(hours=1)).isoformat(),
            "latestRetrievedAt": (AS_OF - timedelta(minutes=30)).isoformat(),
            "technicalScore": 61.0,
            "riskScore": 30.0,
        },
        "fundamentals": {"coverageRatio": 1.0},
        "valuation": {"reportedAnnualPe": 25.0},
    }


def test_capture_persists_ready_evidence_without_creating_advice() -> None:
    repository = _Repository()
    gate = _Gate(_ready_payload())
    service = RecommendationShadowCaptureService(
        repository=repository,  # type: ignore[arg-type]
        evidence_gate_service=gate,
    )

    result = service.capture(
        symbol=" aapl ",
        as_of=AS_OF,
        captured_at=AS_OF + timedelta(minutes=1),
        benchmark_symbol="SPY",
    )

    assert result["status"] == "captured_for_calibration"
    assert result["snapshotId"] == 42
    assert result["advisoryStatus"] == "no_advice"
    assert gate.calls == [{"symbol": "AAPL", "as_of": AS_OF}]
    assert len(repository.calls) == 1
    call = repository.calls[0]
    assert call["instrument_id"] == 1
    assert call["entry_price"] == 200.0
    assert call["benchmark_symbol"] == "SPY"
    snapshot = call["evidence_snapshot"]
    assert isinstance(snapshot, dict)
    assert "action" not in snapshot
    assert "conviction" not in snapshot


def test_capture_does_not_persist_incomplete_evidence() -> None:
    payload = _ready_payload()
    payload["status"] = "core_evidence_ready"
    payload["blockers"] = ["valuation_not_ready", "calibration_not_validated"]
    repository = _Repository()
    service = RecommendationShadowCaptureService(
        repository=repository,  # type: ignore[arg-type]
        evidence_gate_service=_Gate(payload),
    )

    result = service.capture(
        symbol="AAPL",
        as_of=AS_OF,
        captured_at=AS_OF,
    )

    assert result["status"] == "not_captured"
    assert result["advisoryStatus"] == "no_advice"
    assert repository.calls == []


def test_capture_fails_closed_if_gate_claims_advice_readiness() -> None:
    payload = _ready_payload()
    payload["recommendationCandidateReady"] = True
    service = RecommendationShadowCaptureService(
        repository=_Repository(),  # type: ignore[arg-type]
        evidence_gate_service=_Gate(payload),
    )

    with pytest.raises(RuntimeError, match="habilitar consejo"):
        service.capture(symbol="AAPL", as_of=AS_OF, captured_at=AS_OF)


def test_capture_rejects_market_evidence_retrieved_after_cutoff() -> None:
    payload = _ready_payload()
    market = payload["market"]
    assert isinstance(market, dict)
    market["latestRetrievedAt"] = (AS_OF + timedelta(seconds=1)).isoformat()
    repository = _Repository()
    service = RecommendationShadowCaptureService(
        repository=repository,  # type: ignore[arg-type]
        evidence_gate_service=_Gate(payload),
    )

    with pytest.raises(RuntimeError, match="posterior al corte PIT"):
        service.capture(symbol="AAPL", as_of=AS_OF, captured_at=AS_OF)

    assert repository.calls == []


def test_capture_requires_timezone_aware_cutoff() -> None:
    service = RecommendationShadowCaptureService(
        repository=_Repository(),  # type: ignore[arg-type]
        evidence_gate_service=_Gate(_ready_payload()),
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.capture(symbol="AAPL", as_of=datetime(2026, 1, 10, 20, 0))

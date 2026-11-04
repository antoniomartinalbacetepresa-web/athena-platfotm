from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


@dataclass(frozen=True)
class _Valuation:
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "diagnostic_ready",
            "symbol": "AAPL",
            "instrumentId": 1,
            "entityId": "sec-cik:0000320193",
            "asOf": "2026-09-01T20:30:00+00:00",
            "latestPrice": 200.0,
            "annualDilutedEps": {
                "metric": "fundamental.us-gaap.earningspersharediluted",
                "value": 8.0,
                "availableAt": "2025-11-01T00:00:00+00:00",
                "sourceVersion": "10-K|accession|CY2025",
            },
            "reportedAnnualPe": 25.0,
            "productionEligible": self.production_eligible,
        }


class _ValuationService:
    def __init__(self, *, production_eligible: bool = False) -> None:
        self.production_eligible = production_eligible
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _Valuation:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _Valuation(production_eligible=self.production_eligible)


def test_valuation_endpoint_exposes_diagnostic_without_advice(monkeypatch) -> None:
    fake = _ValuationService()
    monkeypatch.setattr(recommendations, "valuation_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/valuation",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["advisoryStatus"] == "diagnostic_only"
    assert body["data"]["reportedAnnualPe"] == 25.0
    assert body["data"]["productionEligible"] is False
    assert len(fake.calls) == 1
    assert fake.calls[0]["symbol"] == "AAPL"
    assert isinstance(fake.calls[0]["as_of"], datetime)


def test_valuation_endpoint_rejects_naive_as_of_before_service(monkeypatch) -> None:
    fake = _ValuationService()
    monkeypatch.setattr(recommendations, "valuation_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/valuation",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_valuation_endpoint_blocks_accidental_production_eligibility(
    monkeypatch,
) -> None:
    fake = _ValuationService(production_eligible=True)
    monkeypatch.setattr(recommendations, "valuation_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/valuation",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 500
    assert "política de seguridad" in response.json()["detail"]

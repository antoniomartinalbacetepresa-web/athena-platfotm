from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


class FakeLearningStatusService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get_status(
        self,
        *,
        as_of: datetime,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "as_of": as_of,
                "model_version": model_version,
                "horizon_days": horizon_days,
            }
        )
        return {
            "status": "learning_diagnostics_only",
            "automaticModelMutation": False,
        }


@dataclass(frozen=True)
class FakeMarketSignal:
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "diagnostic_ready",
            "symbol": "AAPL",
            "instrumentId": 1,
            "asOf": "2026-09-01T20:30:00+00:00",
            "technicalScore": 61.5,
            "riskScore": 27.0,
            "productionEligible": self.production_eligible,
            "reason": "Diagnóstico point-in-time no calibrado.",
        }


class FakeMarketSignalService:
    def __init__(self, *, production_eligible: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.production_eligible = production_eligible

    def evaluate(self, *, symbol: str, as_of: datetime) -> FakeMarketSignal:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return FakeMarketSignal(production_eligible=self.production_eligible)


@dataclass(frozen=True)
class FakeFundamentalSignal:
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "diagnostic_ready",
            "symbol": "AAPL",
            "instrumentId": 1,
            "entityId": "sec-cik:0000320193",
            "asOf": "2026-09-01T20:30:00+00:00",
            "coverageRatio": 1.0,
            "netMargin": 0.25,
            "productionEligible": self.production_eligible,
            "reason": "Fundamentales point-in-time no calibrados.",
        }


class FakeFundamentalSignalService:
    def __init__(self, *, production_eligible: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.production_eligible = production_eligible

    def evaluate(self, *, symbol: str, as_of: datetime) -> FakeFundamentalSignal:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return FakeFundamentalSignal(production_eligible=self.production_eligible)


def test_market_signal_diagnostic_endpoint_exposes_only_non_productive_evidence(
    monkeypatch,
) -> None:
    fake = FakeMarketSignalService()
    monkeypatch.setattr(recommendations, "market_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/market-signal",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["advisoryStatus"] == "diagnostic_only"
    assert body["data"]["status"] == "diagnostic_ready"
    assert body["data"]["productionEligible"] is False
    assert body["data"]["technicalScore"] == 61.5
    assert len(fake.calls) == 1
    assert fake.calls[0]["symbol"] == "AAPL"
    as_of = fake.calls[0]["as_of"]
    assert isinstance(as_of, datetime)
    assert as_of.utcoffset() is not None


def test_market_signal_diagnostic_endpoint_rejects_naive_as_of(monkeypatch) -> None:
    fake = FakeMarketSignalService()
    monkeypatch.setattr(recommendations, "market_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/market-signal",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_market_signal_diagnostic_endpoint_blocks_accidental_production_flag(
    monkeypatch,
) -> None:
    fake = FakeMarketSignalService(production_eligible=True)
    monkeypatch.setattr(recommendations, "market_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/market-signal",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 500
    assert "política de seguridad" in response.json()["detail"]
    assert len(fake.calls) == 1


def test_market_signal_diagnostic_endpoint_requires_symbol(monkeypatch) -> None:
    fake = FakeMarketSignalService()
    monkeypatch.setattr(recommendations, "market_signal_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/recommendations/diagnostics/market-signal")

    assert response.status_code == 422
    assert fake.calls == []


def test_fundamental_diagnostic_endpoint_exposes_only_non_productive_evidence(
    monkeypatch,
) -> None:
    fake = FakeFundamentalSignalService()
    monkeypatch.setattr(recommendations, "fundamental_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/fundamentals",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["advisoryStatus"] == "diagnostic_only"
    assert body["data"]["status"] == "diagnostic_ready"
    assert body["data"]["productionEligible"] is False
    assert body["data"]["coverageRatio"] == 1.0
    assert body["data"]["netMargin"] == 0.25
    assert len(fake.calls) == 1
    assert fake.calls[0]["symbol"] == "AAPL"
    as_of = fake.calls[0]["as_of"]
    assert isinstance(as_of, datetime)
    assert as_of.utcoffset() is not None


def test_fundamental_diagnostic_endpoint_blocks_accidental_production_flag(
    monkeypatch,
) -> None:
    fake = FakeFundamentalSignalService(production_eligible=True)
    monkeypatch.setattr(recommendations, "fundamental_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/fundamentals",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 500
    assert "política de seguridad" in response.json()["detail"]
    assert len(fake.calls) == 1


def test_fundamental_diagnostic_endpoint_rejects_naive_as_of(monkeypatch) -> None:
    fake = FakeFundamentalSignalService()
    monkeypatch.setattr(recommendations, "fundamental_signal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/fundamentals",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_learning_status_endpoint_forwards_explicit_filters(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={
            "as_of": "2026-09-01T20:30:00+00:00",
            "modelVersion": "athena-v1",
            "horizonDays": 90,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "learning_diagnostics_only",
            "automaticModelMutation": False,
        }
    }
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model_version"] == "athena-v1"
    assert call["horizon_days"] == 90
    assert isinstance(call["as_of"], datetime)
    assert call["as_of"].utcoffset() is not None


def test_learning_status_endpoint_uses_timezone_aware_now(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/recommendations/learning/status")

    assert response.status_code == 200
    assert len(fake.calls) == 1
    as_of = fake.calls[0]["as_of"]
    assert isinstance(as_of, datetime)
    assert as_of.utcoffset() is not None


def test_learning_status_endpoint_rejects_naive_as_of(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={"as_of": "2026-09-01T20:30:00"},
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_learning_status_endpoint_rejects_non_positive_horizon(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={"horizonDays": 0},
    )

    assert response.status_code == 422
    assert fake.calls == []

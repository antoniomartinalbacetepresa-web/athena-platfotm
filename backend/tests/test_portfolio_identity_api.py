from fastapi.testclient import TestClient

from app.main import app


class FakeIdentityResult:
    def __init__(self, *, risk_ready: bool) -> None:
        self._risk_ready = risk_ready

    def to_api_dict(self):
        return {
            "databaseInstrumentId": 7,
            "canonicalInstrumentId": "AAPL@NASDAQ",
            "issuerId": "issuer:apple",
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "currency": "USD",
            "sourceProvider": "yahoo_catalog",
            "retrievedAt": "2026-09-04T18:00:00+00:00",
            "resolutionMethod": (
                "symbol_and_exchange_exact"
                if self._risk_ready
                else "unique_active_symbol"
            ),
            "exchangeVerified": self._risk_ready,
            "isRiskReady": self._risk_ready,
            "isWeightingReady": False,
            "recommendationPolicy": "no_advice",
            "productionEligible": False,
            "automaticTrading": False,
        }


def test_portfolio_identity_api_preserves_passive_risk_contract(monkeypatch) -> None:
    calls = []

    class FakeService:
        def resolve(self, *, symbol, exchange):
            calls.append((symbol, exchange))
            return FakeIdentityResult(risk_ready=True)

    monkeypatch.setattr(
        "app.api.portfolio.PortfolioInstrumentIdentityService",
        FakeService,
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/portfolio/instrument-identity",
        params={"symbol": "AAPL", "exchange": "NASDAQ"},
    )

    assert response.status_code == 200
    assert calls == [("AAPL", "NASDAQ")]
    data = response.json()["data"]
    assert data["canonicalInstrumentId"] == "AAPL@NASDAQ"
    assert data["isRiskReady"] is True
    assert data["isWeightingReady"] is False
    assert data["recommendationPolicy"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["automaticTrading"] is False


def test_portfolio_identity_api_returns_diagnostic_unready_identity(monkeypatch) -> None:
    class FakeService:
        def resolve(self, *, symbol, exchange):
            return FakeIdentityResult(risk_ready=False)

    monkeypatch.setattr(
        "app.api.portfolio.PortfolioInstrumentIdentityService",
        FakeService,
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/portfolio/instrument-identity",
        params={"symbol": "AAPL", "exchange": "NMS"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["resolutionMethod"] == "unique_active_symbol"
    assert data["exchangeVerified"] is False
    assert data["isRiskReady"] is False
    assert data["productionEligible"] is False


def test_portfolio_identity_api_fails_closed_for_unresolvable_identity(monkeypatch) -> None:
    class FakeService:
        def resolve(self, *, symbol, exchange):
            raise ValueError("identidad ambigua")

    monkeypatch.setattr(
        "app.api.portfolio.PortfolioInstrumentIdentityService",
        FakeService,
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/portfolio/instrument-identity",
        params={"symbol": "ABC", "exchange": "UNKNOWN"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "identidad ambigua"


def test_portfolio_identity_api_requires_symbol() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/portfolio/instrument-identity")

    assert response.status_code == 422

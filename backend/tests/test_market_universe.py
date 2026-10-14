from fastapi.testclient import TestClient

from app.api import market
from app.main import app


client = TestClient(app)


def test_market_universe_returns_normalized_data(
    monkeypatch,
) -> None:
    def fake_get_universe():
        return [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "marketCap": 2500000000000.0,
                "country": "United States",
                "exchange": "NASDAQ",
                "exchangeShortName": "NASDAQ",
                "regionKey": "america",
                "issuerId": "apple",
                "instrumentId": "AAPL@NASDAQ",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "sector": "Technology",
                "industry": "Consumer Electronics",
            }
        ]

    monkeypatch.setattr(
        market.market_universe_service,
        "get_universe",
        fake_get_universe,
    )

    response = client.get(
        "/api/v1/market/universe"
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "marketCap": 2500000000000.0,
                "country": "United States",
                "exchange": "NASDAQ",
                "exchangeShortName": "NASDAQ",
                "regionKey": "america",
                "issuerId": "apple",
                "instrumentId": "AAPL@NASDAQ",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "sector": "Technology",
                "industry": "Consumer Electronics",
            }
        ]
    }


def test_market_universe_can_return_empty_list(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        market.market_universe_service,
        "get_universe",
        lambda: [],
    )

    response = client.get(
        "/api/v1/market/universe"
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
    }


def test_market_universe_allows_missing_market_cap(
    monkeypatch,
) -> None:
    def fake_get_universe():
        return [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "marketCap": None,
                "country": "United States",
                "exchange": "NASDAQ",
                "exchangeShortName": "NASDAQ",
                "regionKey": "america",
                "issuerId": "apple",
                "instrumentId": "AAPL@NASDAQ",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "sector": "Technology",
                "industry": "Consumer Electronics",
            }
        ]

    monkeypatch.setattr(
        market.market_universe_service,
        "get_universe",
        fake_get_universe,
    )

    response = client.get(
        "/api/v1/market/universe"
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["marketCap"] is None


def test_market_universe_returns_502_for_provider_error(
    monkeypatch,
) -> None:
    def fake_get_universe():
        raise RuntimeError(
            "Yahoo unavailable"
        )

    monkeypatch.setattr(
        market.market_universe_service,
        "get_universe",
        fake_get_universe,
    )

    response = client.get(
        "/api/v1/market/universe"
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "No se pudo obtener el universo "
            "desde la fuente de mercado."
        ),
    }


def test_market_universe_status_returns_quality_report(
    monkeypatch,
) -> None:
    class FakeReport:
        def to_api_dict(self):
            return {
                "activeCount": 120,
                "marketCapReadyCount": 90,
                "countryReadyCount": 100,
                "globallyUsableCount": 80,
                "usableCoverage": 2 / 3,
                "regionCounts": {
                    "america": 40,
                    "europe": 25,
                    "asia": 15,
                },
                "representedRegions": [
                    "america",
                    "europe",
                    "asia",
                ],
                "requiredRegions": [
                    "america",
                    "europe",
                    "asia",
                ],
                "isGlobalReady": True,
                "usingFallback": False,
            }

    monkeypatch.setattr(
        market.market_universe_service,
        "get_quality_report",
        lambda: FakeReport(),
    )

    response = client.get(
        "/api/v1/market/universe/status"
    )

    assert response.status_code == 200
    assert response.json()["data"]["activeCount"] == 120
    assert response.json()["data"]["isGlobalReady"] is True
    assert response.json()["data"]["usingFallback"] is False


def test_market_universe_status_returns_502_for_quality_error(
    monkeypatch,
) -> None:
    def fake_get_quality_report():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        market.market_universe_service,
        "get_quality_report",
        fake_get_quality_report,
    )

    response = client.get(
        "/api/v1/market/universe/status"
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "No se pudo evaluar la calidad "
            "del universo de mercado."
        ),
    }

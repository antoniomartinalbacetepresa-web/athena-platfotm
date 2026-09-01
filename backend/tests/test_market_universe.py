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

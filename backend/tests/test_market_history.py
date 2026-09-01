from fastapi.testclient import TestClient

from app.api import market
from app.main import app


client = TestClient(app)


def test_market_history_returns_normalized_data(
    monkeypatch,
) -> None:
    def fake_get_history(
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        assert symbol == "AAPL"
        assert from_date == "2026-08-27"
        assert to_date == "2026-08-28"

        return [
            {
                "symbol": "AAPL",
                "timestamp": "2026-08-27T04:00:00+00:00",
                "open": 310.55,
                "high": 315.40,
                "low": 309.40,
                "close": 314.58,
                "adjustedClose": 314.58,
                "volume": 32419200.0,
                "change": None,
                "changePercentage": None,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-08-28T04:00:00+00:00",
                "open": 316.85,
                "high": 322.37,
                "low": 315.45,
                "close": 319.70,
                "adjustedClose": 319.70,
                "volume": 38609800.0,
                "change": None,
                "changePercentage": None,
            },
        ]

    monkeypatch.setattr(
        market.market_service,
        "get_history",
        fake_get_history,
    )

    response = client.get(
        "/api/v1/market/history",
        params={
            "symbol": "AAPL",
            "from": "2026-08-27",
            "to": "2026-08-28",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "symbol": "AAPL",
                "timestamp": "2026-08-27T04:00:00+00:00",
                "open": 310.55,
                "high": 315.40,
                "low": 309.40,
                "close": 314.58,
                "adjustedClose": 314.58,
                "volume": 32419200.0,
                "change": None,
                "changePercentage": None,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-08-28T04:00:00+00:00",
                "open": 316.85,
                "high": 322.37,
                "low": 315.45,
                "close": 319.70,
                "adjustedClose": 319.70,
                "volume": 38609800.0,
                "change": None,
                "changePercentage": None,
            },
        ]
    }


def test_market_history_can_return_empty_list(
    monkeypatch,
) -> None:
    def fake_get_history(
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        return []

    monkeypatch.setattr(
        market.market_service,
        "get_history",
        fake_get_history,
    )

    response = client.get(
        "/api/v1/market/history",
        params={"symbol": "UNKNOWN"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
    }


def test_market_history_returns_400_for_value_error(
    monkeypatch,
) -> None:
    def fake_get_history(
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        raise ValueError(
            "Fecha no válida."
        )

    monkeypatch.setattr(
        market.market_service,
        "get_history",
        fake_get_history,
    )

    response = client.get(
        "/api/v1/market/history",
        params={
            "symbol": "AAPL",
            "from": "invalid",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Fecha no válida.",
    }


def test_market_history_returns_502_for_provider_error(
    monkeypatch,
) -> None:
    def fake_get_history(
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        raise RuntimeError(
            "Yahoo unavailable"
        )

    monkeypatch.setattr(
        market.market_service,
        "get_history",
        fake_get_history,
    )

    response = client.get(
        "/api/v1/market/history",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "No se pudo obtener el histórico "
            "desde la fuente de mercado."
        ),
    }


def test_market_history_requires_symbol() -> None:
    response = client.get(
        "/api/v1/market/history"
    )

    assert response.status_code == 422

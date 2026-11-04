from fastapi.testclient import TestClient

from app.api import market
from app.main import app


client = TestClient(app)


def test_market_quote_returns_normalized_data(
    monkeypatch,
) -> None:
    def fake_get_quote(symbol: str):
        assert symbol == "AAPL"

        return {
            "symbol": "AAPL",
            "timestamp": "2026-08-30T12:45:18+00:00",
            "open": 316.85,
            "high": 322.37,
            "low": 315.45,
            "close": 319.70,
            "adjustedClose": 319.70,
            "volume": 38609800.0,
            "change": 5.12,
            "changePercentage": 1.6275,
        }

    monkeypatch.setattr(
        market.market_service,
        "get_quote",
        fake_get_quote,
    )

    response = client.get(
        "/api/v1/market/quote",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "symbol": "AAPL",
            "timestamp": "2026-08-30T12:45:18+00:00",
            "open": 316.85,
            "high": 322.37,
            "low": 315.45,
            "close": 319.70,
            "adjustedClose": 319.70,
            "volume": 38609800.0,
            "change": 5.12,
            "changePercentage": 1.6275,
        }
    }


def test_market_quote_can_return_null(
    monkeypatch,
) -> None:
    def fake_get_quote(symbol: str):
        return None

    monkeypatch.setattr(
        market.market_service,
        "get_quote",
        fake_get_quote,
    )

    response = client.get(
        "/api/v1/market/quote",
        params={"symbol": "UNKNOWN"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": None,
    }


def test_market_quote_returns_400_for_value_error(
    monkeypatch,
) -> None:
    def fake_get_quote(symbol: str):
        raise ValueError(
            "El símbolo no puede estar vacío."
        )

    monkeypatch.setattr(
        market.market_service,
        "get_quote",
        fake_get_quote,
    )

    response = client.get(
        "/api/v1/market/quote",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "El símbolo no puede estar vacío.",
    }


def test_market_quote_returns_502_for_provider_error(
    monkeypatch,
) -> None:
    def fake_get_quote(symbol: str):
        raise RuntimeError(
            "Yahoo unavailable"
        )

    monkeypatch.setattr(
        market.market_service,
        "get_quote",
        fake_get_quote,
    )

    response = client.get(
        "/api/v1/market/quote",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "No se pudo obtener la cotización "
            "desde la fuente de mercado."
        ),
    }


def test_market_quote_enriches_exact_listing(monkeypatch) -> None:
    quote = {
        "symbol": "AAPL", "exchange": "NMS", "currency": "USD",
        "sourceProvider": "yahoo", "quoteType": "EQUITY",
    }
    monkeypatch.setattr(market.market_service, "get_quote", lambda _: dict(quote))
    monkeypatch.setattr(
        market.quote_identity_service, "resolve",
        lambda _: {"canonicalIdentityStatus": "matched_internal_listing", "instrumentId": 17},
    )
    response = client.get("/api/v1/market/quote", params={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["data"]["instrumentId"] == 17


def test_market_quote_identity_outage_never_fabricates_match(monkeypatch) -> None:
    quote = {
        "symbol": "AAPL", "exchange": "NMS", "currency": "USD",
        "sourceProvider": "yahoo", "quoteType": "EQUITY",
    }
    monkeypatch.setattr(market.market_service, "get_quote", lambda _: dict(quote))

    def unavailable(_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(market.quote_identity_service, "resolve", unavailable)
    response = client.get("/api/v1/market/quote", params={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["data"]["canonicalIdentityStatus"] == "unresolved"
    assert "instrumentId" not in response.json()["data"]


def test_market_quote_requires_symbol() -> None:
    response = client.get(
        "/api/v1/market/quote"
    )

    assert response.status_code == 422


def test_market_quote_rejects_provider_symbol_mismatch(monkeypatch) -> None:
    """A provider response for a different ticker cannot reach Market."""
    monkeypatch.setattr(
        market.market_service, "get_quote",
        lambda _: {"symbol": "MSFT", "close": 200.0, "sourceProvider": "yahoo"},
    )
    response = client.get("/api/v1/market/quote", params={"symbol": "AAPL"})
    assert response.status_code == 502
    assert "identidad incompatible" in response.json()["detail"]


def test_market_quote_strips_untrusted_identity_if_database_unavailable(monkeypatch) -> None:
    """An upstream provider must not impersonate the internal identity resolver."""
    quote = {
        "symbol": "AAPL", "exchange": "NMS", "currency": "USD",
        "sourceProvider": "yahoo", "quoteType": "EQUITY",
        "instrumentId": 999, "canonicalIdentityStatus": "matched_internal_listing",
    }
    monkeypatch.setattr(market.market_service, "get_quote", lambda _: dict(quote))

    def unavailable(_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(market.quote_identity_service, "resolve", unavailable)
    response = client.get("/api/v1/market/quote", params={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["data"]["canonicalIdentityStatus"] == "unresolved"
    assert "instrumentId" not in response.json()["data"]


def test_market_quote_identity_only_comes_from_internal_resolver(monkeypatch) -> None:
    quote = {
        "symbol": "AAPL", "exchange": "NMS", "currency": "USD",
        "sourceProvider": "yahoo", "quoteType": "EQUITY",
        "instrumentId": 999, "canonicalIdentityStatus": "matched_internal_listing",
    }
    monkeypatch.setattr(market.market_service, "get_quote", lambda _: dict(quote))

    def resolve(provider_quote):
        assert "instrumentId" not in provider_quote
        assert "canonicalIdentityStatus" not in provider_quote
        return {"canonicalIdentityStatus": "matched_internal_listing", "instrumentId": 17}

    monkeypatch.setattr(market.quote_identity_service, "resolve", resolve)
    response = client.get("/api/v1/market/quote", params={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json()["data"]["instrumentId"] == 17

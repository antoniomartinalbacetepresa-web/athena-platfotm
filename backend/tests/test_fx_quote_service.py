from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.fx_quote_service import FxQuoteService


class FakeMarketService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_quote(self, symbol: str):
        self.calls.append(symbol)
        return deepcopy(self.payload)


def _payload():
    return {
        "symbol": "USDEUR=X",
        "timestamp": "2026-09-02T21:30:00+00:00",
        "retrievedAt": "2026-09-02T21:30:01+00:00",
        "sourceProvider": "yahoo",
        "currency": "EUR",
        "close": 0.86,
    }


def test_fx_current_rate_exposes_provenance_and_direction() -> None:
    market = FakeMarketService(_payload())
    service = FxQuoteService(market_service=market)

    result = service.get_current_rate(base_currency=" usd ", quote_currency="eur")

    assert market.calls == ["USDEUR=X"]
    assert result["status"] == "fx_current_ready"
    assert result["baseCurrency"] == "USD"
    assert result["quoteCurrency"] == "EUR"
    assert result["rate"] == pytest.approx(0.86)
    assert result["sourceProvider"] == "yahoo"
    assert result["sourceSymbol"] == "USDEUR=X"
    assert result["observedAt"] == "2026-09-02T21:30:00+00:00"
    assert result["retrievedAt"] == "2026-09-02T21:30:01+00:00"
    assert result["historicalPointInTimeEligible"] is False
    assert result["policy"]["historicalBackdatingForbidden"] is True


def test_fx_same_currency_is_identity_without_market_call() -> None:
    market = FakeMarketService(None)
    result = FxQuoteService(market_service=market).get_current_rate(
        base_currency="EUR",
        quote_currency="EUR",
    )

    assert market.calls == []
    assert result["status"] == "fx_identity"
    assert result["rate"] == 1.0
    assert result["sourceProvider"] == "identity"
    assert result["historicalPointInTimeEligible"] is False


def test_fx_rejects_invalid_currency_code() -> None:
    with pytest.raises(ValueError, match="ISO"):
        FxQuoteService(market_service=FakeMarketService(None)).get_current_rate(
            base_currency="US",
            quote_currency="EUR",
        )


def test_fx_rejects_wrong_source_symbol() -> None:
    payload = _payload()
    payload["symbol"] = "EURUSD=X"

    with pytest.raises(RuntimeError, match="instrumento distinto"):
        FxQuoteService(market_service=FakeMarketService(payload)).get_current_rate(
            base_currency="USD",
            quote_currency="EUR",
        )


def test_fx_rejects_wrong_quote_currency() -> None:
    payload = _payload()
    payload["currency"] = "USD"

    with pytest.raises(RuntimeError, match="moneda destino"):
        FxQuoteService(market_service=FakeMarketService(payload)).get_current_rate(
            base_currency="USD",
            quote_currency="EUR",
        )


def test_fx_rejects_non_positive_rate() -> None:
    payload = _payload()
    payload["close"] = 0

    with pytest.raises(RuntimeError, match="positiva"):
        FxQuoteService(market_service=FakeMarketService(payload)).get_current_rate(
            base_currency="USD",
            quote_currency="EUR",
        )


def test_fx_rejects_retrieval_before_observation() -> None:
    payload = _payload()
    payload["retrievedAt"] = "2026-09-02T21:29:59+00:00"

    with pytest.raises(RuntimeError, match="preceder"):
        FxQuoteService(market_service=FakeMarketService(payload)).get_current_rate(
            base_currency="USD",
            quote_currency="EUR",
        )

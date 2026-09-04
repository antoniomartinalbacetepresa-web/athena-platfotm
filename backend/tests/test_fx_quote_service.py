from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from app.services.fx_quote_service import FxQuoteService


class FakeMarketService:
    def __init__(self, payload, history=None):
        self.payload = payload
        self.history = history if history is not None else []
        self.calls = []
        self.history_calls = []

    def get_quote(self, symbol: str):
        self.calls.append(symbol)
        return deepcopy(self.payload)

    def get_history(self, symbol: str, from_date=None, to_date=None):
        self.history_calls.append(
            {"symbol": symbol, "from_date": from_date, "to_date": to_date}
        )
        return deepcopy(self.history)


def _payload():
    return {
        "symbol": "USDEUR=X",
        "timestamp": "2026-09-02T21:30:00+00:00",
        "retrievedAt": "2026-09-02T21:30:01+00:00",
        "sourceProvider": "yahoo",
        "currency": "EUR",
        "close": 0.86,
    }


def _historical_payload():
    return {
        "symbol": "USDEUR=X",
        "timestamp": "2026-08-03T00:00:00+00:00",
        "retrievedAt": "2026-09-04T13:00:00+00:00",
        "sourceProvider": "yahoo",
        "close": 0.865,
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


def test_fx_rejects_boolean_rate() -> None:
    payload = _payload()
    payload["close"] = True

    with pytest.raises(RuntimeError, match="numérica"):
        FxQuoteService(market_service=FakeMarketService(payload)).get_current_rate(
            base_currency="USD",
            quote_currency="EUR",
        )


def test_fx_historical_rate_preserves_observed_retrieved_and_cutoff() -> None:
    market = FakeMarketService(None, history=[_historical_payload()])
    service = FxQuoteService(market_service=market)
    cutoff = datetime(2026, 9, 4, 13, 5, tzinfo=timezone.utc)

    result = service.get_historical_rate(
        base_currency="USD",
        quote_currency="EUR",
        observed_on=date(2026, 8, 3),
        knowledge_cutoff=cutoff,
    )

    assert market.history_calls == [
        {
            "symbol": "USDEUR=X",
            "from_date": "2026-08-03",
            "to_date": "2026-08-03",
        }
    ]
    assert result["status"] == "fx_historical_ready"
    assert result["rate"] == pytest.approx(0.865)
    assert result["observedOn"] == "2026-08-03"
    assert result["observedAt"] == "2026-08-03T00:00:00+00:00"
    assert result["retrievedAt"] == "2026-09-04T13:00:00+00:00"
    assert result["knowledgeCutoff"] == "2026-09-04T13:05:00+00:00"
    assert result["sourceProvider"] == "yahoo"
    assert result["sourceSymbol"] == "USDEUR=X"
    assert result["historicalPointInTimeEligible"] is True
    assert result["policy"]["retrievalMustNotExceedKnowledgeCutoff"] is True
    assert result["policy"]["persistObservationForFutureReplay"] is True


def test_fx_historical_rate_fails_closed_when_retrieved_after_cutoff() -> None:
    market = FakeMarketService(None, history=[_historical_payload()])

    with pytest.raises(RuntimeError, match="lookahead"):
        FxQuoteService(market_service=market).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
            knowledge_cutoff=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )


def test_fx_historical_rate_rejects_wrong_observation_date() -> None:
    payload = _historical_payload()
    payload["timestamp"] = "2026-08-04T00:00:00+00:00"

    with pytest.raises(RuntimeError, match="fecha solicitada"):
        FxQuoteService(
            market_service=FakeMarketService(None, history=[payload])
        ).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
        )


def test_fx_historical_rate_rejects_ambiguous_rows() -> None:
    payload = _historical_payload()

    with pytest.raises(RuntimeError, match="ambigua"):
        FxQuoteService(
            market_service=FakeMarketService(None, history=[payload, payload])
        ).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
        )


def test_fx_historical_identity_requires_no_market_data() -> None:
    market = FakeMarketService(None)

    result = FxQuoteService(market_service=market).get_historical_rate(
        base_currency="EUR",
        quote_currency="EUR",
        observed_on=date(2026, 8, 3),
        knowledge_cutoff=datetime(2026, 8, 3, 23, 59, tzinfo=timezone.utc),
    )

    assert market.history_calls == []
    assert result["status"] == "fx_historical_identity"
    assert result["rate"] == 1.0
    assert result["historicalPointInTimeEligible"] is True
    assert result["policy"]["identityConversionRequiresNoMarketObservation"] is True


def test_fx_historical_cutoff_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        FxQuoteService(market_service=FakeMarketService(None)).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
            knowledge_cutoff=datetime(2026, 9, 4, 13, 0),
        )

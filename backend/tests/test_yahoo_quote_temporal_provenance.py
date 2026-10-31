from datetime import datetime, timedelta, timezone

import pandas as pd

from app.services.yahoo_market_service import YahooMarketService


def test_quote_retrieval_is_after_provider_io(monkeypatch):
    provider_read = False

    class FakeTicker:
        @property
        def fast_info(self):
            nonlocal provider_read
            provider_read = True
            return {"lastPrice": 120.0, "previousClose": 100.0}

    class GuardedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert provider_read, "Retrieval time cannot precede provider I/O."
            return datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("app.services.yahoo_market_service.yf.Ticker", lambda symbol: FakeTicker())
    monkeypatch.setattr("app.services.yahoo_market_service.datetime", GuardedDatetime)
    result = YahooMarketService().get_quote("AAPL")
    assert result is not None
    assert result["retrievedAt"] == "2026-10-31T14:00:00+00:00"
    assert result["timestamp"] == result["retrievedAt"]
    assert result["quoteMode"] == "provider_fast_info"
    assert result["priceSessionDate"] is None
    assert result["realTimePriceVerified"] is False
    assert result["historicalPointInTimeEligible"] is False


def test_daily_fallback_preserves_session_date_and_rejects_live_claim(monkeypatch):
    eastern = timezone(timedelta(hours=-4))
    history = pd.DataFrame(
        {"Close": [99.0, 101.0], "Open": [98.0, 100.0]},
        index=pd.DatetimeIndex([
            datetime(2026, 10, 29, 16, 0, tzinfo=eastern),
            datetime(2026, 10, 30, 16, 0, tzinfo=eastern),
        ]),
    )

    class FakeTicker:
        @property
        def fast_info(self):
            return {"lastPrice": None, "previousClose": None}

        def history(self, **kwargs):
            assert kwargs["period"] == "5d"
            return history

    monkeypatch.setattr("app.services.yahoo_market_service.yf.Ticker", lambda symbol: FakeTicker())
    result = YahooMarketService().get_quote("AAPL")
    assert result is not None
    assert result["close"] == 101.0
    assert result["change"] == 2.0
    assert result["quoteMode"] == "historical_daily_close_fallback"
    assert result["priceSessionDate"] == "2026-10-30"
    assert result["realTimePriceVerified"] is False
    assert result["historicalPointInTimeEligible"] is False
    assert datetime.fromisoformat(result["retrievedAt"]).tzinfo is not None


def test_nonpositive_prices_do_not_create_a_current_quote(monkeypatch):
    history = pd.DataFrame(
        {"Close": [-1.0]},
        index=pd.DatetimeIndex([datetime(2026, 10, 30, tzinfo=timezone.utc)]),
    )

    class InvalidTicker:
        @property
        def fast_info(self):
            return {"lastPrice": 0.0, "previousClose": -1.0}

        def history(self, **kwargs):
            return history

    monkeypatch.setattr("app.services.yahoo_market_service.yf.Ticker", lambda symbol: InvalidTicker())
    assert YahooMarketService().get_quote("AAPL") is None

    class ValidTicker:
        @property
        def fast_info(self):
            return {"lastPrice": 101.0, "previousClose": 0.0}

    monkeypatch.setattr("app.services.yahoo_market_service.yf.Ticker", lambda symbol: ValidTicker())
    result = YahooMarketService().get_quote("AAPL")
    assert result is not None
    assert result["close"] == 101.0
    assert result["change"] is None
    assert result["changePercentage"] is None


def test_future_daily_candle_is_rejected(monkeypatch):
    history = pd.DataFrame(
        {"Close": [101.0]},
        index=pd.DatetimeIndex([datetime(2099, 1, 1, tzinfo=timezone.utc)]),
    )

    class FakeTicker:
        @property
        def fast_info(self):
            return {"lastPrice": None}

        def history(self, **kwargs):
            return history

    monkeypatch.setattr("app.services.yahoo_market_service.yf.Ticker", lambda symbol: FakeTicker())
    assert YahooMarketService().get_quote("AAPL") is None

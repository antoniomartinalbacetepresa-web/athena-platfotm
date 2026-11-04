from datetime import datetime

from app.services.yahoo_market_service import YahooMarketService


def test_quote_declares_real_source_and_retrieval_time(monkeypatch) -> None:
    service = YahooMarketService()

    class FakeTicker:
        @property
        def fast_info(self):
            return {
                "lastPrice": 320.0,
                "previousClose": 315.0,
                "open": 316.0,
                "dayHigh": 322.0,
                "dayLow": 314.0,
                "lastVolume": 38_000_000,
            }

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_quote("aapl")

    assert result is not None
    assert result["sourceProvider"] == "yahoo"
    assert result["retrievedAt"] == result["timestamp"]

    retrieved_at = datetime.fromisoformat(result["retrievedAt"])
    assert retrieved_at.tzinfo is not None


def test_provider_id_is_stable_and_explicit() -> None:
    assert YahooMarketService.PROVIDER_ID == "yahoo"

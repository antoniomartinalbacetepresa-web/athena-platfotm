from app.services.yahoo_fx_service import FxRate
from app.services.yahoo_market_universe_service import (
    YahooMarketUniverseService,
)


class FakeFxService:
    def __init__(
        self,
        rates: dict[str, float] | None = None,
    ) -> None:
        self._rates = rates or {}

    def convert_to_usd(
        self,
        amount: float,
        currency: str,
    ) -> float:
        rate = self._rates.get(
            currency,
            1.0,
        )

        return amount * rate


def test_seed_universe_contains_three_regions() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    regions = {
        asset["regionKey"]
        for asset in service._SEED_UNIVERSE
    }

    assert regions == {
        "america",
        "europe",
        "asia",
    }


def test_seed_universe_contains_expected_symbols() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    symbols = {
        asset["symbol"]
        for asset in service._SEED_UNIVERSE
    }

    assert {
        "AAPL",
        "SAP.DE",
        "7203.T",
        "005930.KS",
    }.issubset(symbols)


def test_get_universe_normalizes_market_cap_to_usd(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService(
            {
                "EUR": 1.2,
            }
        )
    )

    def fake_get_market_data(
        symbol: str,
    ) -> dict[str, object]:
        return {
            "marketCap": 1000.0,
            "currency": "EUR",
        }

    monkeypatch.setattr(
        service,
        "_get_market_data",
        fake_get_market_data,
    )

    result = service.get_universe()

    assert len(result) == len(
        service._SEED_UNIVERSE
    )

    for asset in result:
        assert asset["marketCap"] == 1200.0
        assert asset["marketCapLocal"] == 1000.0
        assert asset["currency"] == "EUR"
        assert asset["marketCapCurrency"] == "USD"


def test_get_universe_preserves_configured_fields(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    monkeypatch.setattr(
        service,
        "_get_market_data",
        lambda symbol: {
            "marketCap": 1000.0,
            "currency": "USD",
        },
    )

    result = service.get_universe()

    apple = next(
        asset
        for asset in result
        if asset["symbol"] == "AAPL"
    )

    assert apple["companyName"] == "Apple Inc."
    assert apple["country"] == "United States"
    assert apple["exchange"] == "NASDAQ"
    assert apple["exchangeShortName"] == "NASDAQ"
    assert apple["regionKey"] == "america"
    assert apple["issuerId"] == "apple"
    assert apple["instrumentId"] == "AAPL@NASDAQ"
    assert apple["instrumentType"] == "common_stock"
    assert apple["isPrimaryListing"] is True
    assert apple["sector"] == "Technology"
    assert apple["industry"] == "Consumer Electronics"
    assert apple["marketCap"] == 1000.0
    assert apple["marketCapLocal"] == 1000.0
    assert apple["currency"] == "USD"
    assert apple["marketCapCurrency"] == "USD"


def test_get_universe_accepts_missing_market_cap(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    monkeypatch.setattr(
        service,
        "_get_market_data",
        lambda symbol: {
            "marketCap": None,
            "currency": "USD",
        },
    )

    result = service.get_universe()

    assert result

    for asset in result:
        assert asset["marketCap"] is None
        assert asset["marketCapLocal"] is None
        assert asset["currency"] == "USD"
        assert asset["marketCapCurrency"] == "USD"


def test_get_universe_accepts_missing_currency(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    monkeypatch.setattr(
        service,
        "_get_market_data",
        lambda symbol: {
            "marketCap": 1000.0,
            "currency": None,
        },
    )

    result = service.get_universe()

    assert result

    for asset in result:
        assert asset["marketCap"] is None
        assert asset["marketCapLocal"] == 1000.0
        assert asset["currency"] is None
        assert asset["marketCapCurrency"] == "USD"


def test_convert_market_cap_to_usd_returns_converted_value() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService(
            {
                "JPY": 0.00625,
            }
        )
    )

    result = service._convert_market_cap_to_usd(
        market_cap_local=16000.0,
        currency="JPY",
    )

    assert result == 100.0


def test_convert_market_cap_to_usd_returns_none_for_missing_cap() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._convert_market_cap_to_usd(
        market_cap_local=None,
        currency="USD",
    )

    assert result is None


def test_convert_market_cap_to_usd_returns_none_for_missing_currency() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._convert_market_cap_to_usd(
        market_cap_local=1000.0,
        currency=None,
    )

    assert result is None


def test_convert_market_cap_to_usd_returns_none_when_fx_fails() -> None:
    class FailingFxService:
        def convert_to_usd(
            self,
            amount: float,
            currency: str,
        ) -> float:
            raise RuntimeError(
                "FX unavailable"
            )

    service = YahooMarketUniverseService(
        fx_service=FailingFxService()
    )

    result = service._convert_market_cap_to_usd(
        market_cap_local=1000.0,
        currency="EUR",
    )

    assert result is None


def test_get_market_data_reads_current_yfinance_keys(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    class FakeFastInfo:
        def get(self, key: str):
            values = {
                "marketCap": 2500000000.0,
                "market_cap": None,
                "currency": "usd",
            }

            return values.get(key)

    class FakeTicker:
        @property
        def fast_info(self):
            return FakeFastInfo()

    monkeypatch.setattr(
        "app.services.yahoo_market_universe_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service._get_market_data(
        "AAPL"
    )

    assert result == {
        "marketCap": 2500000000.0,
        "currency": "USD",
    }


def test_get_market_data_supports_legacy_market_cap_key(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    class FakeFastInfo:
        def get(self, key: str):
            values = {
                "marketCap": None,
                "market_cap": 1800000000.0,
                "currency": "eur",
            }

            return values.get(key)

    class FakeTicker:
        @property
        def fast_info(self):
            return FakeFastInfo()

    monkeypatch.setattr(
        "app.services.yahoo_market_universe_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service._get_market_data(
        "SAP.DE"
    )

    assert result == {
        "marketCap": 1800000000.0,
        "currency": "EUR",
    }


def test_get_market_data_returns_nulls_when_yahoo_fails(
    monkeypatch,
) -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    class FakeTicker:
        @property
        def fast_info(self):
            raise RuntimeError(
                "Yahoo unavailable"
            )

    monkeypatch.setattr(
        "app.services.yahoo_market_universe_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service._get_market_data(
        "AAPL"
    )

    assert result == {
        "marketCap": None,
        "currency": None,
    }


def test_normalize_currency_trims_and_uppercases() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._normalize_currency(
        "  eur  "
    )

    assert result == "EUR"


def test_normalize_currency_accepts_none() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._normalize_currency(
        None
    )

    assert result is None


def test_normalize_currency_rejects_empty_value() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._normalize_currency(
        "   "
    )

    assert result is None


def test_to_positive_float_accepts_positive_number() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._to_positive_float(
        "123.45"
    )

    assert result == 123.45


def test_to_positive_float_rejects_zero() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._to_positive_float(
        0
    )

    assert result is None


def test_to_positive_float_rejects_negative_number() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._to_positive_float(
        -100
    )

    assert result is None


def test_to_positive_float_rejects_invalid_value() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._to_positive_float(
        "not-a-number"
    )

    assert result is None


def test_to_positive_float_rejects_none() -> None:
    service = YahooMarketUniverseService(
        fx_service=FakeFxService()
    )

    result = service._to_positive_float(
        None
    )

    assert result is None

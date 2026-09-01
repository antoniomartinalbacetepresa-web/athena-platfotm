from datetime import date

import pytest

from app.services.yahoo_market_service import YahooMarketService


def test_inclusive_to_exclusive_date_adds_one_day() -> None:
    service = YahooMarketService()

    result = service._inclusive_to_exclusive_date(
        "2026-08-28"
    )

    assert result == "2026-08-29"


def test_inclusive_to_exclusive_date_handles_month_change() -> None:
    service = YahooMarketService()

    result = service._inclusive_to_exclusive_date(
        "2026-08-31"
    )

    assert result == "2026-09-01"


def test_inclusive_to_exclusive_date_handles_year_change() -> None:
    service = YahooMarketService()

    result = service._inclusive_to_exclusive_date(
        "2026-12-31"
    )

    assert result == "2027-01-01"


def test_inclusive_to_exclusive_date_accepts_none() -> None:
    service = YahooMarketService()

    result = service._inclusive_to_exclusive_date(
        None
    )

    assert result is None


def test_inclusive_to_exclusive_date_rejects_invalid_date() -> None:
    service = YahooMarketService()

    with pytest.raises(
        ValueError,
        match=(
            "La fecha debe tener formato YYYY-MM-DD "
            "y ser una fecha válida."
        ),
    ):
        service._inclusive_to_exclusive_date(
            "2026-02-30"
        )


def test_parse_date_returns_date() -> None:
    service = YahooMarketService()

    result = service._parse_date(
        "2026-08-28"
    )

    assert result == date(
        2026,
        8,
        28,
    )


def test_parse_date_accepts_none() -> None:
    service = YahooMarketService()

    result = service._parse_date(
        None
    )

    assert result is None


def test_parse_date_rejects_invalid_format() -> None:
    service = YahooMarketService()

    with pytest.raises(
        ValueError,
        match=(
            "La fecha debe tener formato YYYY-MM-DD "
            "y ser una fecha válida."
        ),
    ):
        service._parse_date(
            "28-08-2026"
        )


def test_parse_date_rejects_invalid_calendar_date() -> None:
    service = YahooMarketService()

    with pytest.raises(
        ValueError,
        match=(
            "La fecha debe tener formato YYYY-MM-DD "
            "y ser una fecha válida."
        ),
    ):
        service._parse_date(
            "2026-02-30"
        )


def test_validate_date_range_accepts_ascending_range() -> None:
    service = YahooMarketService()

    service._validate_date_range(
        date(2026, 8, 27),
        date(2026, 8, 28),
    )


def test_validate_date_range_accepts_same_date() -> None:
    service = YahooMarketService()

    service._validate_date_range(
        date(2026, 8, 28),
        date(2026, 8, 28),
    )


def test_validate_date_range_accepts_missing_from_date() -> None:
    service = YahooMarketService()

    service._validate_date_range(
        None,
        date(2026, 8, 28),
    )


def test_validate_date_range_accepts_missing_to_date() -> None:
    service = YahooMarketService()

    service._validate_date_range(
        date(2026, 8, 28),
        None,
    )


def test_validate_date_range_rejects_descending_range() -> None:
    service = YahooMarketService()

    with pytest.raises(
        ValueError,
        match=(
            "La fecha inicial no puede ser posterior "
            "a la fecha final."
        ),
    ):
        service._validate_date_range(
            date(2026, 8, 29),
            date(2026, 8, 28),
        )


def test_normalize_symbol_trims_and_uppercases() -> None:
    service = YahooMarketService()

    result = service._normalize_symbol(
        "  aapl  "
    )

    assert result == "AAPL"


def test_normalize_symbol_rejects_empty_symbol() -> None:
    service = YahooMarketService()

    with pytest.raises(
        ValueError,
        match="El símbolo no puede estar vacío.",
    ):
        service._normalize_symbol("   ")


def test_get_fast_info_value_prefers_current_key() -> None:
    service = YahooMarketService()

    fast_info = {
        "lastPrice": 320.0,
        "last_price": 300.0,
    }

    result = service._get_fast_info_value(
        fast_info,
        "lastPrice",
        "last_price",
    )

    assert result == 320.0


def test_get_fast_info_value_supports_legacy_key() -> None:
    service = YahooMarketService()

    fast_info = {
        "lastPrice": None,
        "last_price": 300.0,
    }

    result = service._get_fast_info_value(
        fast_info,
        "lastPrice",
        "last_price",
    )

    assert result == 300.0


def test_get_quote_reads_current_yfinance_keys(
    monkeypatch,
) -> None:
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
                "lastVolume": 38000000,
            }

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_quote(
        "aapl"
    )

    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["open"] == 316.0
    assert result["high"] == 322.0
    assert result["low"] == 314.0
    assert result["close"] == 320.0
    assert result["adjustedClose"] == 320.0
    assert result["volume"] == 38000000.0
    assert result["change"] == 5.0
    assert result["changePercentage"] == pytest.approx(
        1.5873015873015872
    )


def test_get_quote_supports_legacy_yfinance_keys(
    monkeypatch,
) -> None:
    service = YahooMarketService()

    class FakeTicker:
        @property
        def fast_info(self):
            return {
                "last_price": 200.0,
                "previous_close": 195.0,
                "open": 196.0,
                "day_high": 202.0,
                "day_low": 194.0,
                "last_volume": 1000000,
            }

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_quote(
        "TEST"
    )

    assert result is not None
    assert result["close"] == 200.0
    assert result["open"] == 196.0
    assert result["high"] == 202.0
    assert result["low"] == 194.0
    assert result["volume"] == 1000000.0
    assert result["change"] == 5.0
    assert result["changePercentage"] == pytest.approx(
        2.564102564102564
    )


def test_get_quote_does_not_use_history_when_fast_info_has_price(
    monkeypatch,
) -> None:
    service = YahooMarketService()

    class FakeTicker:
        @property
        def fast_info(self):
            return {
                "lastPrice": 100.0,
                "previousClose": 99.0,
                "open": 99.5,
                "dayHigh": 101.0,
                "dayLow": 98.5,
                "lastVolume": 500000,
            }

        def history(self, *args, **kwargs):
            raise AssertionError(
                "History should not be called."
            )

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_quote(
        "TEST"
    )

    assert result is not None
    assert result["close"] == 100.0


def test_to_float_accepts_numeric_string() -> None:
    service = YahooMarketService()

    result = service._to_float(
        "123.45"
    )

    assert result == 123.45


def test_to_float_rejects_invalid_value() -> None:
    service = YahooMarketService()

    result = service._to_float(
        "not-a-number"
    )

    assert result is None


def test_to_float_rejects_nan() -> None:
    service = YahooMarketService()

    result = service._to_float(
        float("nan")
    )

    assert result is None

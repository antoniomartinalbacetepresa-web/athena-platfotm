from typing import Any

import pytest

from app.services.yahoo_regional_universe_source import (
    YahooRegionalUniverseSource,
)


class FakeFx:
    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates

    def convert_to_usd(self, *, amount: float, currency: str) -> float:
        if currency not in self.rates:
            raise ValueError("unsupported")
        return amount * self.rates[currency]


def fake_query(operator: str, operand: list[Any]):
    return operator, operand


def test_source_maps_regions_and_converts_market_cap() -> None:
    calls: list[dict[str, Any]] = []

    def screen(query, **kwargs):
        calls.append({"query": query, **kwargs})
        return {
            "total": 1,
            "quotes": [
                {
                    "symbol": "SAP.DE",
                    "longName": "SAP SE",
                    "quoteType": "EQUITY",
                    "exchange": "GER",
                    "currency": "EUR",
                    "marketCap": 200.0,
                }
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("de",),
        page_size=100,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"EUR": 1.2}),
    )

    assets = source.get_instruments()

    assert len(assets) == 1
    asset = assets[0]
    assert asset["symbol"] == "SAP.DE"
    assert asset["country"] == "Germany"
    assert asset["regionKey"] == "europe"
    assert asset["marketCapLocal"] == 200.0
    assert asset["marketCap"] == 240.0
    assert asset["marketCapCurrency"] == "EUR"
    assert calls[0]["sortField"] == "intradaymarketcap"
    assert calls[0]["sortAsc"] is False


def test_source_paginates_until_total_is_reached() -> None:
    offsets: list[int] = []

    def screen(query, **kwargs):
        offset = kwargs["offset"]
        offsets.append(offset)
        if offset == 0:
            return {
                "total": 3,
                "quotes": [
                    {
                        "symbol": "A.T",
                        "quoteType": "EQUITY",
                        "exchange": "JPX",
                        "currency": "JPY",
                        "marketCap": 100.0,
                    },
                    {
                        "symbol": "B.T",
                        "quoteType": "EQUITY",
                        "exchange": "JPX",
                        "currency": "JPY",
                        "marketCap": 90.0,
                    },
                ],
            }
        return {
            "total": 3,
            "quotes": [
                {
                    "symbol": "C.T",
                    "quoteType": "EQUITY",
                    "exchange": "JPX",
                    "currency": "JPY",
                    "marketCap": 80.0,
                }
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("jp",),
        page_size=2,
        max_pages_per_region=3,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"JPY": 0.01}),
    )

    assets = source.get_instruments()

    assert offsets == [0, 2]
    assert [asset["symbol"] for asset in assets] == ["A.T", "B.T", "C.T"]


def test_source_exhaustive_mode_reads_until_market_is_exhausted() -> None:
    offsets: list[int] = []

    def screen(query, **kwargs):
        offset = kwargs["offset"]
        offsets.append(offset)
        pages = {
            0: ["A", "B"],
            2: ["C", "D"],
            4: ["E"],
        }
        symbols = pages.get(offset, [])
        return {
            "total": 5,
            "quotes": [
                {
                    "symbol": f"{symbol}.DE",
                    "quoteType": "EQUITY",
                    "exchange": "GER",
                    "currency": "EUR",
                    "marketCap": 100.0 - offset,
                }
                for symbol in symbols
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("de",),
        page_size=2,
        max_pages_per_region=None,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"EUR": 1.0}),
    )

    assets = source.get_instruments()

    assert offsets == [0, 2, 4]
    assert len(assets) == 5


def test_source_exhaustive_mode_stops_on_repeated_page_and_reports_progress() -> None:
    offsets: list[int] = []
    events: list[dict[str, Any]] = []

    repeated_quotes = [
        {
            "symbol": "A.DE",
            "quoteType": "EQUITY",
            "exchange": "GER",
            "currency": "EUR",
            "marketCap": 100.0,
        },
        {
            "symbol": "B.DE",
            "quoteType": "EQUITY",
            "exchange": "GER",
            "currency": "EUR",
            "marketCap": 90.0,
        },
    ]

    def screen(query, **kwargs):
        offsets.append(kwargs["offset"])
        return {
            "total": None,
            "quotes": repeated_quotes,
        }

    source = YahooRegionalUniverseSource(
        regions=("de",),
        page_size=2,
        max_pages_per_region=None,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"EUR": 1.0}),
        progress_callback=events.append,
    )

    assets = source.get_instruments()

    assert offsets == [0, 2]
    assert len(assets) == 2
    assert [event["status"] for event in events] == [
        "page_completed",
        "repeated_page",
    ]
    assert events[0]["page"] == 1
    assert events[0]["received"] == 2
    assert events[0]["newSymbols"] == 2
    assert events[0]["accumulated"] == 2
    assert events[1]["page"] == 2
    assert events[1]["newSymbols"] == 0


def test_source_exhaustive_mode_stops_after_two_pages_without_new_symbols() -> None:
    offsets: list[int] = []
    events: list[dict[str, Any]] = []

    pages = {
        0: ["A", "B"],
        2: ["A", "C"],
        4: ["B", "C"],
        6: ["A", "B"],
        8: ["D", "E"],
    }

    def screen(query, **kwargs):
        offset = kwargs["offset"]
        offsets.append(offset)
        return {
            "total": 50,
            "quotes": [
                {
                    "symbol": f"{symbol}.US",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                    "currency": "USD",
                    "marketCap": 100.0,
                }
                for symbol in pages[offset]
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("us",),
        page_size=2,
        max_pages_per_region=None,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"USD": 1.0}),
        progress_callback=events.append,
    )

    assets = source.get_instruments()

    assert offsets == [0, 2, 4, 6]
    assert {asset["symbol"] for asset in assets} == {"A.US", "B.US", "C.US"}
    assert [event["newSymbols"] for event in events] == [2, 1, 0, 0]
    assert events[-1]["status"] == "no_new_symbols"


def test_source_explicit_page_limit_does_not_use_stagnation_guard() -> None:
    offsets: list[int] = []

    def screen(query, **kwargs):
        offset = kwargs["offset"]
        offsets.append(offset)
        return {
            "total": 10,
            "quotes": [
                {
                    "symbol": "A.L",
                    "quoteType": "EQUITY",
                    "exchange": "LSE",
                    "currency": "GBP",
                    "marketCap": 100.0,
                },
                {
                    "symbol": f"{offset}.L",
                    "quoteType": "EQUITY",
                    "exchange": "LSE",
                    "currency": "GBP",
                    "marketCap": 90.0,
                },
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("gb",),
        page_size=2,
        max_pages_per_region=3,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({"GBP": 1.0}),
    )

    assets = source.get_instruments()

    assert offsets == [0, 2, 4]
    assert len(assets) == 4


def test_source_skips_non_equity_and_keeps_unknown_fx_unconverted() -> None:
    def screen(query, **kwargs):
        return {
            "total": 2,
            "quotes": [
                {
                    "symbol": "ETF.L",
                    "quoteType": "ETF",
                    "exchange": "LSE",
                    "currency": "GBP",
                    "marketCap": 500.0,
                },
                {
                    "symbol": "PLC.L",
                    "quoteType": "EQUITY",
                    "exchange": "LSE",
                    "currency": "GBP",
                    "marketCap": 400.0,
                },
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("gb",),
        page_size=10,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=FakeFx({}),
    )

    assets = source.get_instruments()

    assert len(assets) == 1
    assert assets[0]["symbol"] == "PLC.L"
    assert assets[0]["marketCapLocal"] == 400.0
    assert assets[0]["marketCap"] is None


def test_source_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="page_size"):
        YahooRegionalUniverseSource(page_size=251)

    with pytest.raises(ValueError, match="max_pages_per_region"):
        YahooRegionalUniverseSource(max_pages_per_region=0)

    source = YahooRegionalUniverseSource(
        regions=("xx",),
        screen_function=lambda *args, **kwargs: {},
        query_factory=fake_query,
    )

    with pytest.raises(ValueError, match="no soportada"):
        source.get_instruments()

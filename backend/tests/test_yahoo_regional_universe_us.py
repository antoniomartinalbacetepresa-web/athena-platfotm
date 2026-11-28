from __future__ import annotations

from typing import Any

from app.services.yahoo_regional_universe_source import (
    YahooRegionalUniverseSource,
)


class IdentityFx:
    def convert_to_usd(self, *, amount: float, currency: str) -> float:
        assert currency == "USD"
        return amount


def fake_query(operator: str, operand: list[Any]):
    return operator, operand


def test_default_regions_include_united_states() -> None:
    assert "us" in YahooRegionalUniverseSource.DEFAULT_REGIONS


def test_us_region_maps_to_america_with_us_market_cap() -> None:
    def screen(query, **kwargs):
        return {
            "total": 1,
            "quotes": [
                {
                    "symbol": "AAPL",
                    "longName": "Apple Inc.",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                    "currency": "USD",
                    "marketCap": 4_000_000_000_000,
                }
            ],
        }

    source = YahooRegionalUniverseSource(
        regions=("us",),
        page_size=10,
        screen_function=screen,
        query_factory=fake_query,
        fx_service=IdentityFx(),
    )

    assets = source.get_instruments()

    assert len(assets) == 1
    asset = assets[0]
    assert asset["symbol"] == "AAPL"
    assert asset["country"] == "United States"
    assert asset["regionKey"] == "america"
    assert asset["marketCap"] == 4_000_000_000_000
    assert asset["marketCapLocal"] == 4_000_000_000_000

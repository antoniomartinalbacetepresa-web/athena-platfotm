from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)


class FakeFallback:
    def __init__(self) -> None:
        self.calls = 0

    def get_universe(self) -> list[dict[str, Any]]:
        self.calls += 1
        return []


def test_ready_catalog_serves_only_globally_usable_rows(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    repository = InstrumentRepository(database=database)

    repository.upsert_many(
        [
            {
                "symbol": "USA",
                "companyName": "America",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "marketCap": 10_000,
            },
            {
                "symbol": "EUR",
                "companyName": "Europe",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "XETRA",
                "marketCap": 8_000,
            },
            {
                "symbol": "ASI",
                "companyName": "Asia",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "marketCap": 7_000,
            },
            {
                "symbol": "CATALOG_ONLY",
                "companyName": "Catalog only",
                "exchangeShortName": "NASDAQ",
                "sourceProvider": "nasdaq_trader",
            },
        ]
    )

    fallback = FakeFallback()
    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
        minimum_global_usable_count=3,
        minimum_usable_per_region=1,
        minimum_usable_coverage=0.5,
    )

    universe = service.get_universe()
    report = service.get_quality_report()

    assert fallback.calls == 0
    assert {asset["symbol"] for asset in universe} == {
        "USA",
        "EUR",
        "ASI",
    }
    assert report.active_count == 4
    assert report.globally_usable_count == 3
    assert report.usable_coverage == 0.75
    assert report.is_global_ready is True

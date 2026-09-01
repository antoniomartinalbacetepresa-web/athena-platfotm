from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)


class FakeFallback:
    def __init__(self, universe: list[dict[str, Any]]) -> None:
        self.universe = universe
        self.calls = 0

    def get_universe(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.universe


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena_test.db")
    database.initialize()
    return database


def test_persisted_universe_prefers_ready_global_catalog(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    repository.upsert_many(
        [
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "country": "United States",
                "exchange": "NASDAQ",
                "exchangeShortName": "NASDAQ",
                "regionKey": "america",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "marketCap": 3_000_000_000_000,
                "currency": "USD",
                "sourceProvider": "catalog",
                "isActive": True,
            },
            {
                "symbol": "SAP.DE",
                "companyName": "SAP SE",
                "country": "Germany",
                "exchange": "XETRA",
                "exchangeShortName": "XETRA",
                "regionKey": "europe",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "marketCap": 300_000_000_000,
                "currency": "EUR",
                "sourceProvider": "catalog",
                "isActive": True,
            },
            {
                "symbol": "7203.T",
                "companyName": "Toyota Motor Corporation",
                "country": "Japan",
                "exchange": "TOKYO",
                "exchangeShortName": "TSE",
                "regionKey": "asia",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "marketCap": 400_000_000_000,
                "currency": "JPY",
                "sourceProvider": "catalog",
                "isActive": True,
            },
            {
                "symbol": "OLD",
                "companyName": "Inactive Company",
                "country": "United States",
                "exchange": "NYSE",
                "exchangeShortName": "NYSE",
                "regionKey": "america",
                "marketCap": 100_000_000,
                "sourceProvider": "catalog",
                "isActive": False,
            },
        ]
    )
    fallback = FakeFallback(
        [{"symbol": "FALLBACK", "companyName": "Fallback"}]
    )

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
    )

    universe = service.get_universe()

    assert fallback.calls == 0
    assert {asset["symbol"] for asset in universe} == {
        "MSFT",
        "SAP.DE",
        "7203.T",
    }
    msft = next(asset for asset in universe if asset["symbol"] == "MSFT")
    assert msft["companyName"] == "Microsoft Corporation"
    assert msft["marketCap"] == 3_000_000_000_000
    assert msft["regionKey"] == "america"
    assert msft["instrumentType"] == "common_stock"
    assert msft["isPrimaryListing"] is True
    assert msft["sourceProvider"] == "catalog"


def test_persisted_universe_falls_back_when_catalog_is_empty(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    fallback_universe = [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "regionKey": "america",
        }
    ]
    fallback = FakeFallback(fallback_universe)

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
    )

    universe = service.get_universe()

    assert universe == fallback_universe
    assert fallback.calls == 1


def test_persisted_universe_falls_back_when_catalog_is_not_global_ready(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "regionKey": "america",
            "instrumentType": "common_stock",
            "sourceProvider": "nasdaq_trader",
            "isActive": True,
        }
    )
    fallback_universe = [
        {
            "symbol": "SAFE",
            "companyName": "Safe fallback",
            "regionKey": "america",
        }
    ]
    fallback = FakeFallback(fallback_universe)

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
    )

    universe = service.get_universe()

    assert universe == fallback_universe
    assert fallback.calls == 1


def test_quality_report_explains_catalog_readiness(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    repository.upsert_many(
        [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NASDAQ",
                "marketCap": 3_000_000_000_000,
            },
            {
                "symbol": "SAP.DE",
                "companyName": "SAP SE",
                "country": "Germany",
                "regionKey": "europe",
                "exchangeShortName": "XETRA",
                "marketCap": 300_000_000_000,
            },
            {
                "symbol": "7203.T",
                "companyName": "Toyota Motor Corporation",
                "country": "Japan",
                "regionKey": "asia",
                "exchangeShortName": "TSE",
                "marketCap": 400_000_000_000,
            },
            {
                "symbol": "NO_CAP",
                "companyName": "Missing Market Cap",
                "country": "United States",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "NO_COUNTRY",
                "companyName": "Missing Country",
                "regionKey": "america",
                "exchangeShortName": "NYSE",
                "marketCap": 1_000_000_000,
            },
        ]
    )

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=FakeFallback([]),
    )

    report = service.get_quality_report()
    api_report = report.to_api_dict()

    assert report.active_count == 5
    assert report.market_cap_ready_count == 4
    assert report.country_ready_count == 4
    assert report.globally_usable_count == 3
    assert report.region_counts == {
        "america": 1,
        "europe": 1,
        "asia": 1,
    }
    assert report.represented_regions == (
        "america",
        "europe",
        "asia",
    )
    assert report.is_global_ready is True
    assert report.using_fallback is False
    assert api_report["usableCoverage"] == 0.6


def test_quality_report_marks_incomplete_catalog_as_fallback(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    repository.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
            "regionKey": "america",
        }
    )

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=FakeFallback([]),
    )

    report = service.get_quality_report()

    assert report.active_count == 1
    assert report.market_cap_ready_count == 0
    assert report.country_ready_count == 0
    assert report.globally_usable_count == 0
    assert report.represented_regions == ()
    assert report.is_global_ready is False
    assert report.using_fallback is True

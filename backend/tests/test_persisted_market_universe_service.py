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


def _low_threshold_service(
    database: AthenaDatabase,
    fallback: FakeFallback,
) -> PersistedMarketUniverseService:
    return PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
        minimum_global_usable_count=3,
        minimum_usable_per_region=1,
        minimum_usable_coverage=0.5,
    )


def _insert_three_regions(repository: InstrumentRepository) -> None:
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
        ]
    )


def test_persisted_universe_prefers_catalog_when_configured_thresholds_pass(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    _insert_three_regions(repository)
    fallback = FakeFallback(
        [{"symbol": "FALLBACK", "companyName": "Fallback"}]
    )

    service = _low_threshold_service(database, fallback)
    universe = service.get_universe()

    assert fallback.calls == 0
    assert {asset["symbol"] for asset in universe} == {
        "MSFT",
        "SAP.DE",
        "7203.T",
    }


def test_default_thresholds_reject_tiny_three_region_catalog(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    _insert_three_regions(repository)
    fallback_universe = [
        {"symbol": "SAFE", "companyName": "Safe fallback"}
    ]
    fallback = FakeFallback(fallback_universe)

    service = PersistedMarketUniverseService(
        database=database,
        fallback_service=fallback,
    )

    assert service.get_universe() == fallback_universe
    report = service.get_quality_report()
    assert report.globally_usable_count == 3
    assert report.is_global_ready is False
    assert report.using_fallback is True


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
    _insert_three_regions(repository)
    repository.upsert_many(
        [
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

    service = _low_threshold_service(
        database,
        FakeFallback([]),
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
    assert api_report["minimumGlobalUsableCount"] == 3
    assert api_report["minimumUsablePerRegion"] == 1
    assert api_report["minimumUsableCoverage"] == 0.5


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


def test_quality_thresholds_validate_configuration(tmp_path: Path) -> None:
    database = _database(tmp_path)

    try:
        PersistedMarketUniverseService(
            database=database,
            minimum_global_usable_count=0,
        )
    except ValueError as exc:
        assert "minimum_global_usable_count" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para umbral global inválido.")

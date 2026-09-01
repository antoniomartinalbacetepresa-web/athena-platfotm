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


def test_persisted_universe_prefers_active_catalog(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = InstrumentRepository(database=database)
    repository.upsert_many(
        [
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "exchange": "NASDAQ",
                "exchangeShortName": "NASDAQ",
                "regionKey": "america",
                "instrumentType": "common_stock",
                "isPrimaryListing": True,
                "marketCap": 3_000_000_000_000,
                "currency": "USD",
                "sourceProvider": "nasdaq_trader",
                "isActive": True,
            },
            {
                "symbol": "OLD",
                "companyName": "Inactive Company",
                "exchange": "NYSE",
                "exchangeShortName": "NYSE",
                "sourceProvider": "nasdaq_trader",
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
    assert len(universe) == 1
    assert universe[0]["symbol"] == "MSFT"
    assert universe[0]["companyName"] == "Microsoft Corporation"
    assert universe[0]["marketCap"] == 3_000_000_000_000
    assert universe[0]["regionKey"] == "america"
    assert universe[0]["instrumentType"] == "common_stock"
    assert universe[0]["isPrimaryListing"] is True
    assert universe[0]["sourceProvider"] == "nasdaq_trader"


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

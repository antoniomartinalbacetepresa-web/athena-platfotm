from pathlib import Path
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.instrument_source_membership_repository import (
    InstrumentSourceMembershipRepository,
)
from app.repositories.universe_import_run_repository import (
    UniverseImportRunRepository,
)
from app.services.global_universe_import_service import GlobalUniverseImportService
from app.services.source_aware_universe_import_service import (
    SourceAwareUniverseImportService,
)
from app.services.yahoo_catalog_enrichment_service import (
    YahooCatalogEnrichmentService,
)


class FakeMetadata:
    source_id = "yahoo"

    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self.data = data

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        value = self.data[symbol]
        if isinstance(value, Exception):
            raise value
        return value


class FakeFx:
    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates

    def convert_to_usd(self, *, amount: float, currency: str) -> float:
        if currency not in self.rates:
            raise ValueError("unsupported")
        return amount * self.rates[currency]


def _build(tmp_path: Path, metadata: FakeMetadata, fx: FakeFx):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    memberships = InstrumentSourceMembershipRepository(database=database)
    runs = UniverseImportRunRepository(database=database)
    base_import = GlobalUniverseImportService(
        repository=instruments,
        run_repository=runs,
    )
    source_aware = SourceAwareUniverseImportService(
        import_service=base_import,
        instrument_repository=instruments,
        membership_repository=memberships,
    )
    enrichment = YahooCatalogEnrichmentService(
        instrument_repository=instruments,
        import_service=source_aware,
        metadata_service=metadata,
        fx_service=fx,
    )
    return enrichment, instruments, memberships


def _seed(repository: InstrumentRepository, symbol: str) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Seed",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
            "sourceProvider": "nasdaq_trader",
        }
    )


def test_enrichment_converts_market_cap_and_classifies_region(tmp_path: Path) -> None:
    metadata = FakeMetadata(
        {
            "AAPL": {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
                "instrumentType": "common_stock",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "currency": "USD",
                "marketCapLocal": 3_000.0,
                "marketCapCurrency": "USD",
                "sourceProvider": "yahoo",
            }
        }
    )
    enrichment, instruments, memberships = _build(
        tmp_path,
        metadata,
        FakeFx({"USD": 1.0}),
    )
    instrument_id = _seed(instruments, "AAPL")

    report = enrichment.enrich(limit=10)
    stored = instruments.get_by_id(instrument_id)

    assert report.enriched == 1
    assert report.failed == 0
    assert stored is not None
    assert stored["company_name"] == "Apple Inc."
    assert stored["country"] == "United States"
    assert stored["region_key"] == "america"
    assert stored["market_cap_local"] == 3_000.0
    assert stored["market_cap_usd"] == 3_000.0
    assert stored["sector"] == "Technology"
    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "yahoo",
    ]


def test_unsupported_fx_keeps_usd_market_cap_unknown(tmp_path: Path) -> None:
    metadata = FakeMetadata(
        {
            "TEST": {
                "symbol": "TEST",
                "companyName": "Test PLC",
                "country": "United Kingdom",
                "currency": "GBP",
                "marketCapLocal": 1_000.0,
                "marketCapCurrency": "GBP",
                "sourceProvider": "yahoo",
            }
        }
    )
    enrichment, instruments, _ = _build(
        tmp_path,
        metadata,
        FakeFx({}),
    )
    instrument_id = _seed(instruments, "TEST")

    report = enrichment.enrich(limit=10)
    stored = instruments.get_by_id(instrument_id)

    assert report.enriched == 1
    assert stored is not None
    assert stored["region_key"] == "europe"
    assert stored["market_cap_local"] == 1_000.0
    assert stored["market_cap_usd"] is None


def test_one_metadata_failure_does_not_abort_batch(tmp_path: Path) -> None:
    metadata = FakeMetadata(
        {
            "AAA": RuntimeError("Yahoo unavailable"),
            "BBB": {
                "symbol": "BBB",
                "companyName": "BBB Corp",
                "country": "Japan",
                "currency": "JPY",
                "marketCapLocal": 10_000.0,
                "marketCapCurrency": "JPY",
                "sourceProvider": "yahoo",
            },
        }
    )
    enrichment, instruments, _ = _build(
        tmp_path,
        metadata,
        FakeFx({"JPY": 0.01}),
    )
    _seed(instruments, "AAA")
    bbb_id = _seed(instruments, "BBB")

    report = enrichment.enrich(limit=10)
    bbb = instruments.get_by_id(bbb_id)

    assert report.attempted == 2
    assert report.enriched == 1
    assert report.failed == 1
    assert report.failures[0]["symbol"] == "AAA"
    assert bbb is not None
    assert bbb["region_key"] == "asia"
    assert bbb["market_cap_usd"] == 100.0


def test_complete_rows_can_be_skipped(tmp_path: Path) -> None:
    metadata = FakeMetadata({})
    enrichment, instruments, _ = _build(
        tmp_path,
        metadata,
        FakeFx({"USD": 1.0}),
    )
    instruments.upsert(
        {
            "symbol": "DONE",
            "companyName": "Done Corp",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NASDAQ",
            "sector": "Technology",
            "marketCap": 100.0,
            "currency": "USD",
        }
    )

    report = enrichment.enrich(limit=10, incomplete_only=True)

    assert report.candidates == 0
    assert report.attempted == 0
    assert report.import_report is None

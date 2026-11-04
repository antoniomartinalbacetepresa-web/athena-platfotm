from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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


@dataclass
class FakeSource:
    source_id: str
    instruments: list[dict[str, Any]]

    def get_instruments(self) -> Iterable[dict[str, Any]]:
        return list(self.instruments)


def _service(tmp_path: Path, *, coverage: float = 0.95):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()

    instruments = InstrumentRepository(database=database)
    memberships = InstrumentSourceMembershipRepository(database=database)
    runs = UniverseImportRunRepository(database=database)
    base_import = GlobalUniverseImportService(
        repository=instruments,
        run_repository=runs,
        minimum_reconciliation_coverage=coverage,
    )
    service = SourceAwareUniverseImportService(
        import_service=base_import,
        instrument_repository=instruments,
        membership_repository=memberships,
        minimum_reconciliation_coverage=coverage,
    )
    return service, instruments, memberships


def _asset(symbol: str, *, provider: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "companyName": f"{symbol} Company",
        "exchange": "NASDAQ",
        "exchangeShortName": "NASDAQ",
        "sourceProvider": provider,
    }


def test_import_records_source_membership(tmp_path: Path) -> None:
    service, instruments, memberships = _service(tmp_path)

    report = service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[_asset("AAPL", provider="nasdaq_trader")],
        )
    )

    stored = instruments.get_by_listing("AAPL", "NASDAQ")
    assert stored is not None
    instrument_id = int(stored["id"])

    assert report.accepted == 1
    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "nasdaq_trader",
    ]


def test_enrichment_source_does_not_replace_catalog_membership(tmp_path: Path) -> None:
    service, instruments, memberships = _service(tmp_path)

    service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[_asset("AAPL", provider="nasdaq_trader")],
        )
    )
    service.import_source(
        FakeSource(
            source_id="yahoo",
            instruments=[_asset("AAPL", provider="yahoo")],
        )
    )

    stored = instruments.get_by_listing("AAPL", "NASDAQ")
    assert stored is not None
    instrument_id = int(stored["id"])

    assert stored["source_provider"] == "yahoo"
    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "nasdaq_trader",
        "yahoo",
    ]


def test_membership_reconciliation_survives_source_provider_overwrite(
    tmp_path: Path,
) -> None:
    service, instruments, memberships = _service(tmp_path, coverage=0.5)

    service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[
                _asset("AAPL", provider="nasdaq_trader"),
                _asset("MSFT", provider="nasdaq_trader"),
            ],
        )
    )
    service.import_source(
        FakeSource(
            source_id="yahoo",
            instruments=[
                _asset("AAPL", provider="yahoo"),
                _asset("MSFT", provider="yahoo"),
            ],
        )
    )

    service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[_asset("AAPL", provider="nasdaq_trader")],
        )
    )

    aapl = instruments.get_by_listing("AAPL", "NASDAQ")
    msft = instruments.get_by_listing("MSFT", "NASDAQ")
    assert aapl is not None
    assert msft is not None

    assert memberships.list_active_sources_for_instrument(int(aapl["id"])) == [
        "nasdaq_trader",
        "yahoo",
    ]
    assert memberships.list_active_sources_for_instrument(int(msft["id"])) == [
        "yahoo",
    ]


def test_rejected_import_does_not_reconcile_memberships(tmp_path: Path) -> None:
    service, instruments, memberships = _service(tmp_path, coverage=0.5)

    service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[
                _asset("AAPL", provider="nasdaq_trader"),
                _asset("MSFT", provider="nasdaq_trader"),
            ],
        )
    )

    service.import_source(
        FakeSource(
            source_id="nasdaq_trader",
            instruments=[
                _asset("AAPL", provider="nasdaq_trader"),
                {"symbol": "", "companyName": "Invalid"},
            ],
        )
    )

    msft = instruments.get_by_listing("MSFT", "NASDAQ")
    assert msft is not None
    assert memberships.list_active_sources_for_instrument(int(msft["id"])) == [
        "nasdaq_trader",
    ]

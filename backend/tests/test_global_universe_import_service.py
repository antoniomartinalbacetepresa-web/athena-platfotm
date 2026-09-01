from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.universe_import_run_repository import (
    UniverseImportRunRepository,
)
from app.services.global_universe_import_service import (
    GlobalUniverseImportService,
)


class FakeUniverseSource:
    def __init__(
        self,
        source_id: str,
        instruments: Iterable[dict[str, Any]],
    ) -> None:
        self._source_id = source_id
        self._instruments = list(
            instruments
        )

    @property
    def source_id(self) -> str:
        return self._source_id

    def get_instruments(
        self,
    ) -> Iterable[dict[str, Any]]:
        return list(
            self._instruments
        )


class FailingUniverseSource:
    def __init__(
        self,
        source_id: str,
        *,
        fail_message: str,
    ) -> None:
        self._source_id = source_id
        self._fail_message = fail_message

    @property
    def source_id(self) -> str:
        return self._source_id

    def get_instruments(
        self,
    ) -> Iterable[dict[str, Any]]:
        raise RuntimeError(
            self._fail_message
        )


class PartiallyFailingUniverseSource:
    @property
    def source_id(self) -> str:
        return "partial_source"

    def get_instruments(
        self,
    ) -> Iterable[dict[str, Any]]:
        yield {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NASDAQ",
        }

        yield {
            "companyName": "Invalid Company",
            "exchangeShortName": "NYSE",
        }

        raise RuntimeError(
            "Fallo después de recibir datos parciales."
        )


class FailingInstrumentRepository:
    def count_active_for_source(
        self,
        source_provider: str,
    ) -> int:
        return 0

    def upsert_many(
        self,
        instruments: Iterable[dict[str, Any]],
    ) -> list[int]:
        list(
            instruments
        )

        raise RuntimeError(
            "Fallo simulado de persistencia."
        )

    def upsert_many_with_stats(
        self,
        instruments: Iterable[dict[str, Any]],
    ) -> object:
        list(
            instruments
        )

        raise RuntimeError(
            "Fallo simulado de persistencia."
        )


def _create_service(
    tmp_path: Path,
) -> tuple[
    GlobalUniverseImportService,
    InstrumentRepository,
    UniverseImportRunRepository,
]:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    repository = InstrumentRepository(
        database=database
    )

    run_repository = UniverseImportRunRepository(
        database=database
    )

    service = GlobalUniverseImportService(
        repository=repository,
        run_repository=run_repository,
    )

    return (
        service,
        repository,
        run_repository,
    )


def test_import_source_inserts_valid_instruments(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.source_id == "test_source"
    assert report.received == 2
    assert report.accepted == 2
    assert report.rejected == 0

    assert report.inserted == 2
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 2

    assert report.rejected_records == ()
    assert repository.count() == 2


def test_import_source_normalizes_symbol_and_exchange(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": " aapl ",
                "companyName": "Apple Inc.",
                "exchangeShortName": " nasdaq ",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.accepted == 1

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["symbol"] == "AAPL"
    assert stored["exchange_short_name"] == "NASDAQ"


def test_import_source_sets_source_provider(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="NASDAQ_OFFICIAL",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.source_id == "nasdaq_official"

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["source_provider"] == "nasdaq_official"
    assert stored["retrieved_at"] is not None


def test_explicit_source_provider_is_preserved(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="catalog",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "sourceProvider": "official_exchange",
            },
        ],
    )

    service.import_source(
        source
    )

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert (
        stored["source_provider"]
        == "official_exchange"
    )


def test_import_source_rejects_missing_symbol(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "companyName": "Invalid Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.received == 2
    assert report.accepted == 1
    assert report.rejected == 1

    assert report.inserted == 1
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 1

    assert repository.count() == 1

    assert (
        report.rejected_records[0]["reason"]
        == "symbol es obligatorio."
    )


def test_import_source_rejects_missing_company_name(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "INVALID",
                "exchangeShortName": "NYSE",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.received == 1
    assert report.accepted == 0
    assert report.rejected == 1

    assert report.inserted == 0
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 0

    assert repository.count() == 0

    assert (
        report.rejected_records[0]["reason"]
        == "companyName es obligatorio."
    )


def test_duplicate_listing_in_same_import_is_rejected(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "aapl",
                "companyName": "Apple Duplicate",
                "exchangeShortName": "nasdaq",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.received == 2
    assert report.accepted == 1
    assert report.rejected == 1

    assert report.inserted == 1
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 1

    assert repository.count() == 1

    assert (
        report.rejected_records[0]["reason"]
        == (
            "Cotización duplicada "
            "dentro de la misma importación."
        )
    )


def test_same_symbol_different_exchanges_is_accepted(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "TEST",
                "companyName": "Test Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "TEST",
                "companyName": "Test Company",
                "exchangeShortName": "LSE",
            },
        ],
    )

    report = service.import_source(
        source
    )

    assert report.accepted == 2
    assert report.rejected == 0

    assert report.inserted == 2
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 2

    assert repository.count() == 2


def test_importing_same_catalog_twice_is_idempotent(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "MSFT",
                "companyName": "Microsoft Corporation",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    first_report = service.import_source(
        source
    )

    second_report = service.import_source(
        source
    )

    assert first_report.accepted == 2
    assert first_report.inserted == 2
    assert first_report.updated == 0
    assert first_report.unchanged == 0
    assert first_report.created_or_updated == 2

    assert second_report.accepted == 2
    assert second_report.inserted == 0
    assert second_report.updated == 0
    assert second_report.unchanged == 2
    assert second_report.created_or_updated == 0

    assert repository.count() == 2


def test_second_import_updates_existing_listing(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    first_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "marketCap": 4_000_000_000_000,
            },
        ],
    )

    second_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "marketCap": 4_600_000_000_000,
                "sector": "Technology",
            },
        ],
    )

    first_report = service.import_source(
        first_source
    )

    second_report = service.import_source(
        second_source
    )

    assert first_report.inserted == 1
    assert first_report.updated == 0
    assert first_report.unchanged == 0
    assert first_report.created_or_updated == 1

    assert second_report.inserted == 0
    assert second_report.updated == 1
    assert second_report.unchanged == 0
    assert second_report.created_or_updated == 1

    assert repository.count() == 1

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["market_cap_usd"] == 4_600_000_000_000
    assert stored["sector"] == "Technology"


def test_retrieved_at_only_change_counts_as_unchanged(
    tmp_path: Path,
) -> None:
    service, _, _ = _create_service(
        tmp_path
    )

    first_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "retrievedAt": (
                    "2026-09-01T00:00:00+00:00"
                ),
            },
        ],
    )

    second_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "retrievedAt": (
                    "2026-09-01T01:00:00+00:00"
                ),
            },
        ],
    )

    service.import_source(
        first_source
    )

    second_report = service.import_source(
        second_source
    )

    assert second_report.inserted == 0
    assert second_report.updated == 0
    assert second_report.unchanged == 1
    assert second_report.created_or_updated == 0


def test_mixed_import_reports_real_change_statistics(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "UNCH",
                "companyName": "Unchanged Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "UPD",
                "companyName": "Old Company",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    next_source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "UNCH",
                "companyName": "Unchanged Company",
                "exchangeShortName": "NYSE",
            },
            {
                "symbol": "UPD",
                "companyName": "Updated Company",
                "exchangeShortName": "NASDAQ",
            },
            {
                "symbol": "NEW",
                "companyName": "New Company",
                "exchangeShortName": "NYSE",
            },
        ],
    )

    service.import_source(
        initial_source
    )

    report = service.import_source(
        next_source
    )

    assert report.received == 3
    assert report.accepted == 3
    assert report.rejected == 0

    assert report.inserted == 1
    assert report.updated == 1
    assert report.unchanged == 1

    assert report.created_or_updated == 2

    assert (
        report.inserted
        + report.updated
        + report.unchanged
        == report.accepted
    )

    assert repository.count() == 3


def test_import_sources_handles_multiple_sources(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    america = FakeUniverseSource(
        source_id="america_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    europe = FakeUniverseSource(
        source_id="europe_source",
        instruments=[
            {
                "symbol": "SAP.DE",
                "companyName": "SAP SE",
                "exchangeShortName": "XETRA",
            },
        ],
    )

    reports = service.import_sources(
        [
            america,
            europe,
        ]
    )

    assert len(reports) == 2
    assert reports[0].source_id == "america_source"
    assert reports[1].source_id == "europe_source"

    assert reports[0].inserted == 1
    assert reports[1].inserted == 1

    assert repository.count() == 2


def test_empty_source_produces_empty_report(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="empty_source",
        instruments=[],
    )

    report = service.import_source(
        source
    )

    assert report.received == 0
    assert report.accepted == 0
    assert report.rejected == 0

    assert report.inserted == 0
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 0

    assert repository.count() == 0


def test_source_id_is_required(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="   ",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match="source_id es obligatorio.",
    ):
        service.import_source(
            source
        )

    assert repository.count() == 0


def test_existing_retrieved_at_is_preserved(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    retrieved_at = (
        "2026-08-30T12:00:00+00:00"
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
                "retrievedAt": retrieved_at,
            },
        ],
    )

    service.import_source(
        source
    )

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["retrieved_at"] == retrieved_at


def test_missing_is_active_defaults_to_true(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="test_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    service.import_source(
        source
    )

    stored = repository.get_by_listing(
        "AAPL",
        "NASDAQ",
    )

    assert stored is not None
    assert stored["is_active"] == 1


def test_successful_import_is_audited_as_succeeded(
    tmp_path: Path,
) -> None:
    service, _, run_repository = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="audit_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
            {
                "companyName": "Invalid Company",
                "exchangeShortName": "NYSE",
            },
        ],
    )

    report = service.import_source(
        source
    )

    run = run_repository.latest_for_source(
        "audit_source"
    )

    assert report.inserted == 1
    assert report.updated == 0
    assert report.unchanged == 0
    assert report.created_or_updated == 1

    assert run is not None
    assert run["status"] == "succeeded"
    assert run["received"] == 2
    assert run["accepted"] == 1
    assert run["rejected"] == 1
    assert run["created_or_updated"] == 1
    assert run["completed_at"] is not None
    assert run["error_message"] is None


def test_unchanged_import_audits_zero_created_or_updated(
    tmp_path: Path,
) -> None:
    service, _, run_repository = _create_service(
        tmp_path
    )

    source = FakeUniverseSource(
        source_id="audit_source",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    first_report = service.import_source(
        source
    )

    second_report = service.import_source(
        source
    )

    assert first_report.created_or_updated == 1

    assert second_report.inserted == 0
    assert second_report.updated == 0
    assert second_report.unchanged == 1
    assert second_report.created_or_updated == 0

    latest_run = run_repository.latest_for_source(
        "audit_source"
    )

    assert latest_run is not None
    assert latest_run["status"] == "succeeded"
    assert latest_run["received"] == 1
    assert latest_run["accepted"] == 1
    assert latest_run["rejected"] == 0
    assert latest_run["created_or_updated"] == 0


def test_source_failure_is_audited_and_rethrown(
    tmp_path: Path,
) -> None:
    service, repository, run_repository = _create_service(
        tmp_path
    )

    source = FailingUniverseSource(
        source_id="failing_source",
        fail_message="Fallo simulado de la fuente.",
    )

    with pytest.raises(
        RuntimeError,
        match="Fallo simulado de la fuente.",
    ):
        service.import_source(
            source
        )

    assert repository.count() == 0

    run = run_repository.latest_for_source(
        "failing_source"
    )

    assert run is not None
    assert run["status"] == "failed"
    assert run["received"] == 0
    assert run["accepted"] == 0
    assert run["rejected"] == 0
    assert run["created_or_updated"] == 0
    assert (
        run["error_message"]
        == "Fallo simulado de la fuente."
    )
    assert run["completed_at"] is not None


def test_partial_source_failure_preserves_progress_in_audit(
    tmp_path: Path,
) -> None:
    service, repository, run_repository = _create_service(
        tmp_path
    )

    source = PartiallyFailingUniverseSource()

    with pytest.raises(
        RuntimeError,
        match=(
            "Fallo después de recibir "
            "datos parciales."
        ),
    ):
        service.import_source(
            source
        )

    assert repository.count() == 0

    run = run_repository.latest_for_source(
        "partial_source"
    )

    assert run is not None
    assert run["status"] == "failed"
    assert run["received"] == 2
    assert run["accepted"] == 1
    assert run["rejected"] == 1
    assert run["created_or_updated"] == 0
    assert (
        run["error_message"]
        == (
            "Fallo después de recibir "
            "datos parciales."
        )
    )


def test_persistence_failure_is_audited_and_rethrown(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    run_repository = UniverseImportRunRepository(
        database=database
    )

    service = GlobalUniverseImportService(
        repository=FailingInstrumentRepository(),
        run_repository=run_repository,
    )

    source = FakeUniverseSource(
        source_id="persistence_failure",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="Fallo simulado de persistencia.",
    ):
        service.import_source(
            source
        )

    run = run_repository.latest_for_source(
        "persistence_failure"
    )

    assert run is not None
    assert run["status"] == "failed"
    assert run["received"] == 1
    assert run["accepted"] == 1
    assert run["rejected"] == 0
    assert run["created_or_updated"] == 0
    assert (
        run["error_message"]
        == "Fallo simulado de persistencia."
    )


def test_import_sources_creates_independent_audit_runs(
    tmp_path: Path,
) -> None:
    service, _, run_repository = _create_service(
        tmp_path
    )

    first_source = FakeUniverseSource(
        source_id="first_source",
        instruments=[
            {
                "symbol": "AAA",
                "companyName": "First Company",
                "exchangeShortName": "NYSE",
            },
        ],
    )

    second_source = FakeUniverseSource(
        source_id="second_source",
        instruments=[
            {
                "symbol": "BBB",
                "companyName": "Second Company",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    reports = service.import_sources(
        [
            first_source,
            second_source,
        ]
    )

    assert len(reports) == 2

    first_run = run_repository.latest_for_source(
        "first_source"
    )

    second_run = run_repository.latest_for_source(
        "second_source"
    )

    assert first_run is not None
    assert second_run is not None

    assert first_run["status"] == "succeeded"
    assert second_run["status"] == "succeeded"

    assert first_run["created_or_updated"] == 1
    assert second_run["created_or_updated"] == 1

    assert first_run["id"] != second_run["id"]


def _instrument(
    symbol: str,
    *,
    source_provider: str = "reconcile_source",
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "companyName": f"{symbol} Company",
        "exchangeShortName": "NASDAQ",
        "sourceProvider": source_provider,
    }


def test_first_import_does_not_apply_reconciliation(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=[
                _instrument("AAA"),
                _instrument("BBB"),
            ],
        )
    )

    assert report.deactivated == 0
    assert report.reconciliation_applied is False
    assert repository.count(active_only=True) == 2


def test_complete_follow_up_import_deactivates_missing_listing(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:99],
        )
    )

    missing = repository.get_by_listing(
        "S099",
        "NASDAQ",
    )

    assert report.reconciliation_applied is True
    assert report.deactivated == 1

    assert missing is not None
    assert missing["is_active"] == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 99
    )


def test_empty_follow_up_import_never_reconciles(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(10)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=[],
        )
    )

    assert report.accepted == 0
    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 10
    )


def test_incomplete_follow_up_import_does_not_reconcile(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:40],
        )
    )

    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 100
    )


def test_reconciliation_applies_at_exact_coverage_threshold(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:95],
        )
    )

    assert report.reconciliation_applied is True
    assert report.deactivated == 5

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 95
    )


def test_reconciliation_does_not_apply_below_coverage_threshold(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:94],
        )
    )

    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 100
    )


def test_reconciliation_only_uses_records_owned_by_source(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    mixed_records = [
        *initial_instruments[:40],
        *[
            _instrument(
                f"O{index:03d}",
                source_provider="other_source",
            )
            for index in range(60)
        ],
    ]

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=mixed_records,
        )
    )

    assert report.accepted == 100
    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 100
    )


def test_reappearing_listing_is_reactivated(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    second_report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:99],
        )
    )

    assert second_report.deactivated == 1

    inactive = repository.get_by_listing(
        "S099",
        "NASDAQ",
    )

    assert inactive is not None
    assert inactive["is_active"] == 0

    third_report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    active = repository.get_by_listing(
        "S099",
        "NASDAQ",
    )

    assert third_report.reconciliation_applied is True
    assert third_report.deactivated == 0

    assert active is not None
    assert active["is_active"] == 1


def test_source_failure_never_reconciles_existing_catalog(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(10)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="Fallo de descarga.",
    ):
        service.import_source(
            FailingUniverseSource(
                source_id="reconcile_source",
                fail_message="Fallo de descarga.",
            )
        )

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 10
    )



def test_rejected_records_prevent_reconciliation(
    tmp_path: Path,
) -> None:
    service, repository, _ = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    follow_up_instruments = [
        *initial_instruments[:95],
        {
            "companyName": "Invalid Company",
            "exchangeShortName": "NASDAQ",
            "sourceProvider": "reconcile_source",
        },
    ]

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=follow_up_instruments,
        )
    )

    assert report.received == 96
    assert report.accepted == 95
    assert report.rejected == 1

    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert (
        repository.count_active_for_source(
            "reconcile_source"
        )
        == 100
    )


class FailingCountInstrumentRepository:
    def count_active_for_source(
        self,
        source_provider: str,
    ) -> int:
        raise RuntimeError(
            "Fallo simulado al contar activos."
        )


def test_previous_active_count_failure_is_audited_and_rethrown(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena_test.db"
    )

    database.initialize()

    run_repository = UniverseImportRunRepository(
        database=database
    )

    service = GlobalUniverseImportService(
        repository=FailingCountInstrumentRepository(),
        run_repository=run_repository,
    )

    source = FakeUniverseSource(
        source_id="count_failure",
        instruments=[
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "exchangeShortName": "NASDAQ",
            },
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="Fallo simulado al contar activos.",
    ):
        service.import_source(
            source
        )

    latest_run = run_repository.latest_for_source(
        "count_failure"
    )

    assert latest_run is not None
    assert latest_run["status"] == "failed"
    assert (
        latest_run["error_message"]
        == "Fallo simulado al contar activos."
    )


def test_reconciliation_result_is_persisted_in_audit(
    tmp_path: Path,
) -> None:
    service, _, run_repository = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:95],
        )
    )

    latest_run = run_repository.latest_for_source(
        "reconcile_source"
    )

    assert report.reconciliation_applied is True
    assert report.deactivated == 5

    assert latest_run is not None
    assert latest_run["status"] == "succeeded"
    assert latest_run["deactivated"] == 5
    assert latest_run["reconciliation_applied"] == 1


def test_non_reconciled_result_is_persisted_in_audit(
    tmp_path: Path,
) -> None:
    service, _, run_repository = _create_service(
        tmp_path
    )

    initial_instruments = [
        _instrument(
            f"S{index:03d}"
        )
        for index in range(100)
    ]

    service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments,
        )
    )

    report = service.import_source(
        FakeUniverseSource(
            source_id="reconcile_source",
            instruments=initial_instruments[:94],
        )
    )

    latest_run = run_repository.latest_for_source(
        "reconcile_source"
    )

    assert report.reconciliation_applied is False
    assert report.deactivated == 0

    assert latest_run is not None
    assert latest_run["status"] == "succeeded"
    assert latest_run["deactivated"] == 0
    assert latest_run["reconciliation_applied"] == 0

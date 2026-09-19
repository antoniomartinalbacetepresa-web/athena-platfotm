from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.instrument_source_membership_repository import (
    InstrumentSourceMembershipRepository,
)


def _repositories(tmp_path: Path):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    memberships = InstrumentSourceMembershipRepository(database=database)
    return instruments, memberships


def _instrument_id(repository: InstrumentRepository, symbol: str) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Company",
            "exchangeShortName": "NASDAQ",
        }
    )


def test_same_instrument_can_have_multiple_active_sources(tmp_path: Path) -> None:
    instruments, memberships = _repositories(tmp_path)
    instrument_id = _instrument_id(instruments, "AAPL")

    memberships.mark_seen_many(
        source_id="nasdaq_trader",
        instrument_ids=[instrument_id],
        seen_at="2026-09-01T08:00:00+00:00",
    )
    memberships.mark_seen_many(
        source_id="yahoo",
        instrument_ids=[instrument_id],
        seen_at="2026-09-01T08:05:00+00:00",
    )

    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "nasdaq_trader",
        "yahoo",
    ]


def test_deactivating_one_source_preserves_other_source(tmp_path: Path) -> None:
    instruments, memberships = _repositories(tmp_path)
    instrument_id = _instrument_id(instruments, "AAPL")

    memberships.mark_seen_many(
        source_id="nasdaq_trader",
        instrument_ids=[instrument_id],
    )
    memberships.mark_seen_many(
        source_id="yahoo",
        instrument_ids=[instrument_id],
    )

    deactivated = memberships.deactivate_missing_for_source(
        source_id="nasdaq_trader",
        active_instrument_ids=[],
    )

    assert deactivated == 1
    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "yahoo",
    ]
    assert memberships.count_active_for_source("nasdaq_trader") == 0
    assert memberships.count_active_for_source("yahoo") == 1


def test_mark_seen_reactivates_membership_without_losing_first_seen(tmp_path: Path) -> None:
    instruments, memberships = _repositories(tmp_path)
    instrument_id = _instrument_id(instruments, "AAPL")

    memberships.mark_seen_many(
        source_id="nasdaq_trader",
        instrument_ids=[instrument_id],
        seen_at="2026-09-01T08:00:00+00:00",
    )
    memberships.deactivate_missing_for_source(
        source_id="nasdaq_trader",
        active_instrument_ids=[],
    )
    memberships.mark_seen_many(
        source_id="nasdaq_trader",
        instrument_ids=[instrument_id],
        seen_at="2026-09-01T09:00:00+00:00",
    )

    assert memberships.count_active_for_source("nasdaq_trader") == 1
    assert memberships.list_active_sources_for_instrument(instrument_id) == [
        "nasdaq_trader",
    ]


def test_mark_seen_deduplicates_instrument_ids(tmp_path: Path) -> None:
    instruments, memberships = _repositories(tmp_path)
    instrument_id = _instrument_id(instruments, "AAPL")

    processed = memberships.mark_seen_many(
        source_id="nasdaq_trader",
        instrument_ids=[instrument_id, instrument_id],
    )

    assert processed == 1
    assert memberships.count_active_for_source("nasdaq_trader") == 1


def test_source_id_is_required(tmp_path: Path) -> None:
    _, memberships = _repositories(tmp_path)

    try:
        memberships.count_active_for_source("   ")
    except ValueError as exc:
        assert "source_id" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para source_id vacío.")

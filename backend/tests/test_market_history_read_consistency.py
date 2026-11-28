"""WAL concurrency regressions for live historical diagnostics.

These prove per-report read consistency, not operational 365-day coverage.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService


def _seed(tmp_path: Path) -> tuple[Path, int]:
    database = AthenaDatabase(tmp_path / "history.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "WALTEST",
        "companyName": "WAL Test",
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "WAL",
        "instrumentType": "common_stock",
    })
    return database.database_path, instrument_id


def _interleaved_database(path: Path, instrument_id: int, needle: str):
    writes: list[bool] = []

    class InterleavedDatabase(AthenaDatabase):
        def connect(self) -> sqlite3.Connection:
            connection = super().connect()

            def on_sql(statement: str) -> None:
                if needle not in statement or writes:
                    return
                # A separate WAL writer commits between two SELECTs on the
                # diagnostic connection. No fixture is counted as production.
                with sqlite3.connect(path, timeout=5) as writer:
                    writer.execute(
                        "UPDATE instruments SET is_active = 0 WHERE id = ?",
                        (instrument_id,),
                    )
                writes.append(True)

            connection.set_trace_callback(on_sql)
            return connection

    return InterleavedDatabase(path), writes


def _assert_concurrent_change_committed(path: Path, instrument_id: int) -> None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT is_active FROM instruments WHERE id = ?",
            (instrument_id,),
        ).fetchone()
    assert row == (0,)


def test_live_coverage_uses_one_wal_generation_for_all_totals(tmp_path: Path) -> None:
    path, instrument_id = _seed(tmp_path)
    database, writes = _interleaved_database(
        path, instrument_id,
        "AND LOWER(TRIM(COALESCE(instrument_type, 'unknown'))) NOT IN",
    )
    report = MarketObservationCoverageService(database=database).get_report()
    assert writes == [True]
    _assert_concurrent_change_committed(path, instrument_id)
    # The later eligible count must not see a different catalogue generation
    # than the earlier active count, despite the committed concurrent writer.
    assert report.active_instrument_count == 1
    assert report.history_eligible_instrument_count == 1
    assert report.current_deep_history_instrument_count == 0
    assert report.current_history_depth_ready is False


def test_live_gap_count_and_page_share_one_wal_generation(tmp_path: Path) -> None:
    path, instrument_id = _seed(tmp_path)
    database, writes = _interleaved_database(
        path, instrument_id,
        "SELECT instrument_id, symbol, reason, source_count, best_source_provider",
    )
    report = MarketHistoryGapService(database=database).get_report()
    assert writes == [True]
    _assert_concurrent_change_committed(path, instrument_id)
    assert report.total_blocking_count == 1
    assert report.no_observations_count == 1
    assert len(report.items) == 1
    assert report.items[0].instrument_id == instrument_id
    assert report.items[0].symbol == "WALTEST"

"""Acceptance tests for read-only, point-in-time SQLite coverage snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from scripts.market_history_acceptance_snapshot import parse_cutoff, run_snapshot


def _database(tmp_path: Path) -> tuple[Path, AthenaDatabase]:
    path = tmp_path / "source.db"
    database = AthenaDatabase(path)
    database.initialize()
    return path, database


def _instrument(database: AthenaDatabase, symbol: str = "AAA") -> int:
    return InstrumentRepository(database=database).upsert({
        "symbol": symbol,
        "companyName": symbol,
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "NASDAQ",
        "instrumentType": "common_stock",
    })


def _history(start: datetime) -> list[dict[str, object]]:
    return [
        {"timestamp": (start + timedelta(days=day)).isoformat(), "close": 100.0}
        for day in range(0, 366, 5)
    ]


def test_empty_universe_never_claims_acceptance(tmp_path: Path) -> None:
    path, _ = _database(tmp_path)
    result = run_snapshot(path)
    assert result["historyEligibleInstrumentCount"] == 0
    assert result["totalBlockingCount"] == 0
    assert result["diagnosticReady"] is False
    assert result["productionCoverageClaimed"] is False
    assert result["operationalEvidenceVerified"] is False
    assert len(result["snapshotSha256"]) == 64


def test_missing_history_is_a_blocker_without_mutating_source(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_snapshot(path, as_of=datetime(2026, 10, 24, tzinfo=timezone.utc))
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after
    assert result["historyEligibleInstrumentCount"] == 1
    assert result["currentDeepHistoryInstrumentCount"] == 0
    assert result["totalBlockingCount"] == 1
    assert result["blockingByReason"]["no_observations"] == 1
    assert result["diagnosticReady"] is False


def test_current_365_day_history_is_diagnostic_only(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    instrument_id = _instrument(database)
    start = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=366)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_history(start),
        source_provider="yahoo",
        retrieved_at=cutoff,
    )
    result = run_snapshot(path, as_of=cutoff)
    assert result["historyEligibleInstrumentCount"] == 1
    assert result["currentDeepHistoryInstrumentCount"] == 1
    assert result["totalBlockingCount"] == 0
    assert result["diagnosticReady"] is True
    assert result["productionCoverageClaimed"] is False
    assert result["operationalEvidenceVerified"] is False


def test_late_retrieval_is_not_backdated_at_pit_cutoff(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    instrument_id = _instrument(database)
    start = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    retrieved = start + timedelta(days=366)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_history(start),
        source_provider="yahoo",
        retrieved_at=retrieved,
    )
    result = run_snapshot(path, as_of=retrieved - timedelta(hours=1))
    assert result["currentDeepHistoryInstrumentCount"] == 0
    assert result["totalBlockingCount"] == 1
    assert result["diagnosticReady"] is False


@pytest.mark.parametrize("value", ["2026-10-24", "not-a-date", ""])
def test_cutoff_requires_valid_timezone(value: str) -> None:
    with pytest.raises(ValueError, match="as-of"):
        parse_cutoff(value)


def test_cutoff_normalizes_absolute_instant() -> None:
    assert parse_cutoff("2026-10-24T17:00:00+02:00") == datetime(
        2026, 10, 24, 15, tzinfo=timezone.utc
    )


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        run_snapshot(path)
    assert not path.exists()


def test_mismatched_diagnostics_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    original = MarketHistoryGapService.get_report

    def incorrect(self: MarketHistoryGapService, **kwargs: object):
        return replace(original(self, **kwargs), total_blocking_count=0)

    monkeypatch.setattr(MarketHistoryGapService, "get_report", incorrect)
    with pytest.raises(RuntimeError, match="inconsistentes"):
        run_snapshot(path)

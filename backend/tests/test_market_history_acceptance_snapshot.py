"""Acceptance tests for read-only, point-in-time SQLite coverage snapshots."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from scripts.market_history_acceptance_snapshot import export_blockers_csv, main, parse_cutoff, run_snapshot


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


def test_blocker_pagination_is_deterministic_and_read_only(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    for symbol in ("ZZZ", "AAA", "MMM"):
        _instrument(database, symbol)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cutoff = datetime(2026, 10, 24, tzinfo=timezone.utc)
    first = run_snapshot(path, as_of=cutoff, blocker_limit=2)
    second = run_snapshot(path, as_of=cutoff, blocker_limit=2, blocker_offset=2)
    assert first["totalBlockingCount"] == second["totalBlockingCount"] == 3
    assert [item["symbol"] for item in first["blockingItems"]] == ["AAA", "MMM"]
    assert [item["symbol"] for item in second["blockingItems"]] == ["ZZZ"]
    assert [item["reason"] for item in first["blockingItems"]] == ["no_observations"] * 2
    assert first["blockingPage"] == {
        "limit": 2, "offset": 0, "returnedCount": 2, "hasMore": True,
    }
    assert second["blockingPage"] == {
        "limit": 2, "offset": 2, "returnedCount": 1, "hasMore": False,
    }
    assert first["snapshotSha256"] == second["snapshotSha256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert first["productionCoverageClaimed"] is False


@pytest.mark.parametrize("limit,offset", [
    (0, 0), (1001, 0), (True, 0), (1.5, 0), (1, -1), (1, True), (1, 2.5),
])
def test_blocker_pagination_rejects_invalid_bounds(
    tmp_path: Path, limit: object, offset: object,
) -> None:
    path, _ = _database(tmp_path)
    with pytest.raises(ValueError, match="blocker_"):
        run_snapshot(path, blocker_limit=limit, blocker_offset=offset)


def test_blocker_pagination_beyond_end_is_empty_not_ready(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    result = run_snapshot(path, blocker_limit=2, blocker_offset=100)
    assert result["totalBlockingCount"] == 1
    assert result["blockingItems"] == []
    assert result["blockingPage"]["hasMore"] is False
    assert result["diagnosticReady"] is False


def test_invalid_sqlite_source_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "broken.db"
    path.write_bytes(b"not a sqlite database")
    before = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        run_snapshot(path)
    assert path.read_bytes() == before

def test_future_pit_cutoff_is_rejected_without_touching_source(tmp_path: Path) -> None:
    path, _ = _database(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="fecha futura"):
        run_snapshot(path, as_of=datetime.now(timezone.utc) + timedelta(days=1))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_complete_worklist_from_single_snapshot_is_read_only(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    for symbol in ("DDD", "AAA", "CCC", "BBB", "EEE"):
        _instrument(database, symbol)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_snapshot(
        path, as_of=datetime(2026, 10, 24, tzinfo=timezone.utc),
        blocker_limit=2, all_blockers=True,
    )
    assert result["totalBlockingCount"] == 5
    assert result["blockingExportComplete"] is True
    assert [item["symbol"] for item in result["blockingItems"]] == [
        "AAA", "BBB", "CCC", "DDD", "EEE",
    ]
    assert len({item["instrumentId"] for item in result["blockingItems"]}) == 5
    assert result["blockingPage"] == {
        "limit": 5, "offset": 0, "returnedCount": 5, "hasMore": False,
    }
    assert result["diagnosticReady"] is False
    assert result["productionCoverageClaimed"] is False
    assert result["operationalEvidenceVerified"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_complete_worklist_rejects_offset(tmp_path: Path) -> None:
    path, _ = _database(tmp_path)
    with pytest.raises(ValueError, match="blocker_offset"):
        run_snapshot(path, blocker_offset=1, all_blockers=True)


def test_complete_worklist_fails_closed_on_inconsistent_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, database = _database(tmp_path)
    _instrument(database, "AAA")
    _instrument(database, "BBB")
    original = MarketHistoryGapService.get_report

    def corrupted(self: MarketHistoryGapService, **kwargs: object):
        report = original(self, **kwargs)
        if kwargs.get("offset") == 1:
            return replace(report, total_blocking_count=report.total_blocking_count + 1)
        return report

    monkeypatch.setattr(MarketHistoryGapService, "get_report", corrupted)
    with pytest.raises(RuntimeError, match="inconsistentes"):
        run_snapshot(path, blocker_limit=1, all_blockers=True)


def test_cli_exports_all_and_returns_nonzero_for_unmet_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path, database = _database(tmp_path)
    _instrument(database, "AAA")
    _instrument(database, "BBB")
    monkeypatch.setattr("sys.argv", [
        "market_history_acceptance_snapshot", "--database", str(path),
        "--all-blockers", "--blocker-limit", "1", "--require-history-ready",
    ])
    assert main() == 3
    output = json.loads(capsys.readouterr().out)
    assert output["blockingExportComplete"] is True
    assert output["totalBlockingCount"] == 2
    assert len(output["blockingItems"]) == 2
    assert output["productionCoverageClaimed"] is False


def test_cli_history_gate_is_diagnostic_not_production_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path, database = _database(tmp_path)
    instrument_id = _instrument(database)
    start = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=366)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id, observations=_history(start),
        source_provider="yahoo", retrieved_at=cutoff,
    )
    monkeypatch.setattr("sys.argv", [
        "market_history_acceptance_snapshot", "--database", str(path),
        "--as-of", cutoff.isoformat(), "--all-blockers", "--require-history-ready",
    ])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["diagnosticReady"] is True
    assert output["blockingExportComplete"] is True
    assert output["blockingItems"] == []
    assert output["productionCoverageClaimed"] is False
    assert output["operationalEvidenceVerified"] is False


def test_cli_exports_complete_pit_csv_without_modifying_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path, database = _database(tmp_path)
    for symbol in ("ZZZ", "AAA", "MMM"):
        _instrument(database, symbol)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output = tmp_path / "gaps.csv"
    monkeypatch.setattr("sys.argv", [
        "market_history_acceptance_snapshot", "--database", str(path),
        "--all-blockers", "--blocker-limit", "1",
        "--blocking-csv", str(output), "--require-history-ready",
    ])
    assert main() == 3
    report = json.loads(capsys.readouterr().out)
    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["symbol"] for row in rows] == ["AAA", "MMM", "ZZZ"]
    assert len(rows) == report["totalBlockingCount"] == 3
    assert all(row["asOf"] == report["asOf"] for row in rows)
    assert all(row["snapshotSha256"] == report["snapshotSha256"] for row in rows)
    assert all(row["evidenceStatus"] == "diagnostic_only"
               and row["productionCoverageClaimed"] == "false" for row in rows)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob(".athena-history-gaps-*"))


def test_csv_export_never_overwrites_prior_evidence(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    report = run_snapshot(path, all_blockers=True)
    target = tmp_path / "existing.csv"
    target.write_text("previous evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_blockers_csv(report, target)
    assert target.read_text(encoding="utf-8") == "previous evidence"
    assert not list(tmp_path.glob(".athena-history-gaps-*"))


def test_csv_export_rejects_partial_report_and_spreadsheet_formulas(tmp_path: Path) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    partial = run_snapshot(path)
    with pytest.raises(ValueError, match="íntegra"):
        export_blockers_csv(partial, tmp_path / "partial.csv")
    assert not (tmp_path / "partial.csv").exists()
    complete = run_snapshot(path, all_blockers=True)
    complete["blockingItems"][0]["symbol"] = "=HYPERLINK(\\"https://evil.example\\")"
    target = tmp_path / "safe.csv"
    export_blockers_csv(complete, target)
    with target.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["symbol"].startswith("'=HYPERLINK(")


def test_cli_requires_complete_export_for_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, database = _database(tmp_path)
    _instrument(database)
    target = tmp_path / "should-not-exist.csv"
    monkeypatch.setattr("sys.argv", [
        "market_history_acceptance_snapshot", "--database", str(path),
        "--blocking-csv", str(target),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not target.exists()

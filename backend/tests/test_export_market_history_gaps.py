"""Regression coverage for complete operational market-history gap export."""

from __future__ import annotations

import hashlib
import sqlite3
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.database.read_only_snapshot_database import ReadOnlySnapshotDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService
from scripts.export_corporate_action_reconciliation import _consistent_copy, _sha256_file
from scripts.export_market_history_gaps import export_history_gaps


def _seed(tmp_path):
    database = AthenaDatabase(tmp_path / "market.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    ids = {}
    for symbol, instrument_type in (
        ("AAA", "common_stock"),
        ("BBB", "common_stock"),
        ("CCC", "common_stock"),
        ("ETF1", "etf"),
    ):
        ids[symbol] = instruments.upsert({
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NASDAQ",
            "instrumentType": instrument_type,
        })
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    start = cutoff - timedelta(days=366)
    MarketObservationRepository(database=database).save_many(
        instrument_id=ids["CCC"],
        observations=[
            {"timestamp": (start + timedelta(days=day)).isoformat(), "close": 100.0}
            for day in range(0, 366, 5)
        ],
        source_provider="yahoo",
        retrieved_at=start + timedelta(days=365),
    )
    return database, cutoff


def test_complete_history_gap_export_reconciles_eligible_universe(tmp_path):
    database, cutoff = _seed(tmp_path)
    output = tmp_path / "gaps.jsonl"
    original_hash = hashlib.sha256(database.database_path.read_bytes()).hexdigest()

    result = export_history_gaps(
        database_path=database.database_path, output_path=output,
        as_of=cutoff, page_size=1,
    )
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 3
    metadata, *gaps = rows
    assert metadata["recordType"] == "metadata"
    assert metadata["completeExport"] is True
    assert metadata["eligibleInstrumentCount"] == 3
    assert metadata["currentDeepHistoryInstrumentCount"] == 1
    assert metadata["totalBlockingCount"] == 2
    assert metadata["blockingByReason"]["no_observations"] == 2
    assert metadata["coverage"]["currentDeepHistoryCoverage"] == pytest.approx(1 / 3)
    assert [row["symbol"] for row in gaps] == ["AAA", "BBB"]
    assert all(row["recordType"] == "history_gap" for row in gaps)
    assert result["historyReadyOnSnapshot"] is False
    assert result["productionCoverageClaimed"] is False
    assert result["exportSha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert original_hash == hashlib.sha256(database.database_path.read_bytes()).hexdigest()


def test_history_gap_export_refuses_overwrite_future_cutoff_and_invalid_page(tmp_path):
    database, cutoff = _seed(tmp_path)
    output = tmp_path / "existing.jsonl"
    output.write_text("operator evidence")
    with pytest.raises(FileExistsError):
        export_history_gaps(
            database_path=database.database_path, output_path=output, as_of=cutoff
        )
    assert output.read_text() == "operator evidence"
    with pytest.raises(ValueError, match="future"):
        export_history_gaps(
            database_path=database.database_path, output_path=tmp_path / "future.jsonl",
            as_of=datetime.now(timezone.utc) + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="page_size"):
        export_history_gaps(
            database_path=database.database_path, output_path=tmp_path / "bad.jsonl",
            as_of=cutoff, page_size=0,
        )


def test_history_gap_export_never_publishes_inconsistent_pages(tmp_path, monkeypatch):
    database, cutoff = _seed(tmp_path)
    original = MarketHistoryGapService.get_report

    def inconsistent(self, *, as_of, limit, offset):
        page = original(self, as_of=as_of, limit=limit, offset=offset)
        return replace(page, total_blocking_count=page.total_blocking_count + 1) if offset else page

    monkeypatch.setattr(MarketHistoryGapService, "get_report", inconsistent)
    output = tmp_path / "inconsistent.jsonl"
    with pytest.raises(RuntimeError, match="Inconsistent"):
        export_history_gaps(
            database_path=database.database_path, output_path=output,
            as_of=cutoff, page_size=1,
        )
    assert not output.exists()


def test_history_snapshot_diagnostics_are_read_only_and_schema_checked(tmp_path):
    database, cutoff = _seed(tmp_path)
    snapshot = tmp_path / "immutable-snapshot.db"
    initial_sha = _consistent_copy(database.database_path, snapshot)
    diagnostic = ReadOnlySnapshotDatabase(snapshot)

    # Coverage and each gap page used to call the normal schema initializer,
    # which updates schema_metadata and can change the snapshot SHA mid-export.
    for _ in range(3):
        MarketObservationCoverageService(diagnostic).get_report(as_of=cutoff)
        MarketHistoryGapService(diagnostic).get_report(
            as_of=cutoff, limit=1, offset=0
        )
    assert _sha256_file(snapshot) == initial_sha
    with diagnostic.connect() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                "UPDATE schema_metadata SET value='0' WHERE key='schema_version'"
            )
    assert _sha256_file(snapshot) == initial_sha

    # Outdated snapshots must be rejected, never migrated by a diagnostic.
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            "UPDATE schema_metadata SET value='8' WHERE key='schema_version'"
        )
    with pytest.raises(RuntimeError, match="schema version"):
        diagnostic.initialize()

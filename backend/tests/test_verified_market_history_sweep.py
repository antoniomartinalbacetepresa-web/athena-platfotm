"""Integrated acceptance of the bounded, stable market-history blocker sweep."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.verified_market_history_backfill_service import VerifiedMarketHistoryBackfillService
from app.services import verified_market_history_backfill_service as sweep_module
from scripts import backfill_deep_market_history


class FakeHistoryProvider:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_history(self, symbol, from_date=None, to_date=None):
        self.calls.append(symbol)
        return list(self.responses.get(symbol, []))


def make_database(tmp_path, *symbols):
    database = AthenaDatabase(tmp_path / "operational-test.db")
    database.initialize()
    repository = InstrumentRepository(database=database)
    for symbol in symbols:
        repository.upsert({
            "symbol": symbol, "companyName": symbol, "country": "United States",
            "regionKey": "america", "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
        })
    return database


def history(today: date):
    start = datetime.combine(
        today - timedelta(days=366), time(21), tzinfo=timezone.utc
    )
    return [
        {
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "sourceProvider": "yahoo", "close": 100.0,
        }
        for day in range(0, 366, 5)
    ]


def test_sweep_attempts_every_initial_blocker_once_despite_unresolved_first(
    tmp_path,
):
    database = make_database(tmp_path, "AAA", "BBB", "CCC")
    today = datetime.now(timezone.utc).date()
    provider = FakeHistoryProvider({
        "AAA": [], "BBB": history(today), "CCC": history(today),
    })
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )

    report = service.run_sweep(limit=2, max_batches=2)

    assert provider.calls == ["AAA", "BBB", "CCC"]
    assert report["initialBlockingCount"] == 3
    assert report["attemptedInstrumentCount"] == 3
    assert report["unattemptedInstrumentCount"] == 0
    assert report["remainingBlockingCount"] == 1
    assert report["completeWorklistProcessed"] is True
    assert report["historyReady"] is False
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_can_close_all_persisted_blockers_without_claiming_production(
    tmp_path,
):
    database = make_database(tmp_path, "AAA", "BBB")
    today = datetime.now(timezone.utc).date()
    provider = FakeHistoryProvider({
        "AAA": history(today), "BBB": history(today),
    })
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )

    report = service.run_sweep(limit=1, max_batches=2)

    assert provider.calls == ["AAA", "BBB"]
    assert report["historyReady"] is True
    assert report["remainingBlockingCount"] == 0
    assert report["status"] == "history_criteria_satisfied"
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_reports_unattempted_blockers_at_batch_cap(tmp_path):
    database = make_database(tmp_path, "AAA", "BBB", "CCC")
    today = datetime.now(timezone.utc).date()
    provider = FakeHistoryProvider({"AAA": history(today), "BBB": history(today)})
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )

    report = service.run_sweep(limit=2, max_batches=1)

    assert provider.calls == ["AAA", "BBB"]
    assert report["unattemptedInstrumentCount"] == 1
    assert report["remainingBlockingCount"] == 1
    assert report["completeWorklistProcessed"] is False
    assert report["historyReady"] is False


@pytest.mark.parametrize("limit,batches", [(0, 1), (501, 1), (1, 0), (500, 1001), (True, 1)])
def test_sweep_rejects_unbounded_or_invalid_worklists(tmp_path, limit, batches):
    database = make_database(tmp_path, "AAA")
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=FakeHistoryProvider({}),
    )
    with pytest.raises(ValueError):
        service.run_sweep(limit=limit, max_batches=batches)


def test_cli_sweep_requires_zero_offset(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["backfill_deep_market_history", "--sweep", "--offset", "1"],
    )
    with pytest.raises(ValueError, match="offset"):
        backfill_deep_market_history.main()


def test_cli_sweep_returns_nonzero_until_history_is_ready(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["backfill_deep_market_history", "--sweep", "--limit", "2"],
    )
    monkeypatch.setattr(
        backfill_deep_market_history, "run_sweep",
        lambda **kwargs: {"historyReady": False, "status": "history_criteria_still_blocked"},
    )
    assert backfill_deep_market_history.main() == 3
    assert "history_criteria_still_blocked" in capsys.readouterr().out


def test_sweep_initializes_fresh_database_before_reading_blockers(tmp_path):
    database = AthenaDatabase(tmp_path / "fresh-sweep.db")
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=FakeHistoryProvider({}),
    )
    report = service.run_sweep(limit=2, max_batches=1)
    assert database.database_path.exists()
    assert report["initialBlockingCount"] == 0
    assert report["historyReady"] is False
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_freezes_more_than_1000_blockers_before_writing(tmp_path, monkeypatch):
    """Large eligible universes must not be truncated at the SQL page limit."""
    database = make_database(tmp_path, "AAA")
    today = datetime.now(timezone.utc).date()
    pages = []

    def get_report(_self, *, limit, offset, as_of):
        pages.append((limit, offset))
        assert 1 <= limit <= 1000
        ids = range(offset + 1, min(1001, offset + limit) + 1)
        return SimpleNamespace(
            total_blocking_count=1001,
            items=tuple(SimpleNamespace(instrument_id=i, symbol=f"TEST{i:04d}") for i in ids),
            as_of=as_of.isoformat(),
            minimum_history_days=365,
            maximum_source_gap_days=7,
        )

    monkeypatch.setattr(sweep_module.MarketHistoryGapService, "get_report", get_report)
    # This pagination test synthesizes 1001 blocker IDs without inserting
    # instruments. Supply matching frozen listing identities explicitly;
    # production sweeps must never skip the identity lookup.
    def frozen_get_by_id(_self, instrument_id):
        return {
            "symbol": f"TEST{instrument_id:04d}",
            "exchange_short_name": "NASDAQ",
            "instrument_type": "common_stock",
            "issuer_id": None, "instrument_id": None,
            "currency": None, "is_active": 1,
        }

    monkeypatch.setattr(sweep_module.InstrumentRepository, "get_by_id", frozen_get_by_id)
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=FakeHistoryProvider({}),
        today_provider=lambda: today,
    )
    attempted = []

    def run(*, limit, offset, from_date, to_date, _instrument_ids, _expected_symbols, _expected_identities):
        assert offset == 0
        assert limit == len(_instrument_ids) == len(_expected_symbols) == len(_expected_identities)
        assert all(identity[0] == symbol for identity, symbol in zip(_expected_identities, _expected_symbols))
        assert _expected_symbols == tuple(f"TEST{i:04d}" for i in _instrument_ids)
        attempted.extend(_instrument_ids)
        return SimpleNamespace(
            blockers_after=1001,
            history_ready=False,
            backfill=SimpleNamespace(failed_count=0),
            to_api_dict=lambda: {"status": "diagnostic_only"},
        )

    monkeypatch.setattr(service, "run", run)
    report = service.run_sweep(limit=500, max_batches=3)
    assert pages == [(1000, 0), (1, 1000)]
    assert attempted == list(range(1, 1002))
    assert report["attemptedInstrumentCount"] == 1001
    assert report["unattemptedInstrumentCount"] == 0
    assert report["completeWorklistProcessed"] is True
    assert report["batchCount"] == 3
    assert report["historyReady"] is False
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_fails_closed_if_blocker_worklist_changes_during_freeze(
    tmp_path, monkeypatch,
):
    database = make_database(tmp_path, "AAA")
    today = datetime.now(timezone.utc).date()

    def get_report(_self, *, limit, offset, as_of):
        return SimpleNamespace(
            total_blocking_count=1001 if offset == 0 else 1002,
            items=tuple(SimpleNamespace(instrument_id=i, symbol=f"TEST{i:04d}") for i in
                        range(offset + 1, min(1001, offset + limit) + 1)),
            as_of=as_of.isoformat(),
            minimum_history_days=365,
            maximum_source_gap_days=7,
        )

    monkeypatch.setattr(sweep_module.MarketHistoryGapService, "get_report", get_report)
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=FakeHistoryProvider({}),
        today_provider=lambda: today,
    )
    attempted = []
    monkeypatch.setattr(service, "run", lambda **kwargs: attempted.append(kwargs))
    with pytest.raises(RuntimeError, match="congelación"):
        service.run_sweep(limit=500, max_batches=3)
    assert attempted == []


def test_sweep_freezes_consistent_worklist_when_live_universe_changes_between_pages(
    tmp_path, monkeypatch,
):
    """A new alphabetically earlier live blocker must not displace a frozen ID."""
    database = make_database(tmp_path, "BBB", "CCC", "DDD")
    today = datetime.now(timezone.utc).date()
    provider = FakeHistoryProvider({})
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )
    gap_class = sweep_module.MarketHistoryGapService
    original = gap_class.get_report
    monkeypatch.setattr(gap_class, "MAX_LIMIT", 2)
    inserted = False

    def concurrent_universe_change(self, **kwargs):
        nonlocal inserted
        result = original(self, **kwargs)
        if not inserted and kwargs.get("offset") == 0:
            inserted = True
            InstrumentRepository(database=database).upsert({
                "symbol": "AAA", "companyName": "AAA",
                "country": "United States", "regionKey": "america",
                "exchangeShortName": "NASDAQ", "instrumentType": "common_stock",
            })
        return result

    monkeypatch.setattr(gap_class, "get_report", concurrent_universe_change)
    report = service.run_sweep(limit=1, max_batches=3)

    assert inserted is True
    assert provider.calls == ["BBB", "CCC", "DDD"]
    assert report["initialBlockingCount"] == 3
    assert report["attemptedInstrumentCount"] == 3
    assert report["remainingBlockingCount"] == 4
    assert report["historyReady"] is False
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_empty_frozen_queue_never_writes_new_live_blockers(
    tmp_path, monkeypatch,
):
    """An instrument appearing after freeze is not authorized for this sweep."""
    database = make_database(tmp_path)
    today = datetime.now(timezone.utc).date()
    provider = FakeHistoryProvider({"AAA": history(today)})
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )
    original = sweep_module.MarketHistoryGapService.get_report
    inserted = False

    def insert_after_frozen_query(self, **kwargs):
        nonlocal inserted
        result = original(self, **kwargs)
        if not inserted and result.total_blocking_count == 0:
            inserted = True
            InstrumentRepository(database=database).upsert({
                "symbol": "AAA", "companyName": "AAA",
                "country": "United States", "regionKey": "america",
                "exchangeShortName": "NASDAQ", "instrumentType": "common_stock",
            })
        return result

    monkeypatch.setattr(
        sweep_module.MarketHistoryGapService, "get_report",
        insert_after_frozen_query,
    )
    report = service.run_sweep(limit=2, max_batches=1)

    assert inserted is True
    assert provider.calls == []
    assert report["initialBlockingCount"] == 0
    assert report["attemptedInstrumentCount"] == 0
    assert report["batchCount"] == 0
    assert report["batches"] == []
    assert report["remainingBlockingCount"] == 1
    assert report["historyReady"] is False
    assert report["policy"]["productionEvidenceClaimed"] is False


def test_sweep_no_initial_blockers_is_read_only_and_still_checks_depth(tmp_path):
    """An already complete worklist should not fetch or persist more history."""
    from app.repositories.market_observation_repository import MarketObservationRepository

    database = make_database(tmp_path, "AAA")
    today = datetime.now(timezone.utc).date()
    instrument = InstrumentRepository(database=database).list_active(limit=1, offset=0)[0]
    MarketObservationRepository(database=database).save_many(
        instrument_id=int(instrument["id"]),
        observations=history(today),
        source_provider="yahoo",
        retrieved_at=datetime.now(timezone.utc),
    )
    provider = FakeHistoryProvider({"AAA": []})
    service = VerifiedMarketHistoryBackfillService(
        database=database, history_provider=provider, today_provider=lambda: today,
    )
    report = service.run_sweep(limit=2, max_batches=1)

    assert provider.calls == []
    assert report["initialBlockingCount"] == 0
    assert report["attemptedInstrumentCount"] == 0
    assert report["remainingBlockingCount"] == 0
    assert report["batchCount"] == 0
    assert report["batches"] == []
    assert report["historyReady"] is True
    assert report["policy"]["productionEvidenceClaimed"] is False

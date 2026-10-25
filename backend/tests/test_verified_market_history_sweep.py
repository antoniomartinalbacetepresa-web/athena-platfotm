"""Integrated acceptance of the bounded, stable market-history blocker sweep."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.verified_market_history_backfill_service import VerifiedMarketHistoryBackfillService
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


@pytest.mark.parametrize("limit,batches", [(0, 1), (501, 1), (1, 0), (500, 3), (True, 1)])
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

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_observation_backfill_service import (
    MarketObservationBackfillService,
)


class FakeHistoryProvider:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.date_calls: list[tuple[str, str | None, str | None]] = []

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(symbol)
        self.date_calls.append((symbol, from_date, to_date))
        response = self.responses.get(symbol, [])
        if isinstance(response, Exception):
            raise response
        return list(response)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _insert(
    repository: InstrumentRepository,
    *,
    symbol: str,
    instrument_type: str,
) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": symbol,
            "instrumentType": instrument_type,
        }
    )


def test_backfill_persists_history_and_skips_known_non_equity(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    stock_id = _insert(instruments, symbol="AAA", instrument_type="common_stock")
    _insert(instruments, symbol="ETF1", instrument_type="etf")
    _insert(instruments, symbol="FUND1", instrument_type="fund")

    provider = FakeHistoryProvider(
        {
            "AAA": [
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "close": 100.0,
                    "adjustedClose": 99.5,
                    "volume": 1000,
                }
            ]
        }
    )
    progress: list[dict[str, object]] = []
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
        progress_callback=progress.append,
    )

    report = service.run(limit=10)

    assert report.selected_count == 3
    assert report.persisted_instrument_count == 1
    assert report.skipped_non_equity_count == 2
    assert report.failed_count == 0
    assert report.observations_inserted == 1
    assert report.selection_mode == "active_universe"
    assert provider.calls == ["AAA"]
    assert {item["status"] for item in progress} == {
        "persisted",
        "skipped_non_equity",
    }

    rows = MarketObservationRepository(database=database).list_for_instrument(stock_id)
    assert len(rows) == 1
    assert rows[0]["close"] == 100.0
    assert rows[0]["adjusted_close"] == 99.5


def test_backfill_is_idempotent_and_preserves_first_observation(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    stock_id = _insert(instruments, symbol="AAA", instrument_type="common_stock")
    timestamp = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat()
    provider = FakeHistoryProvider(
        {"AAA": [{"timestamp": timestamp, "close": 100.0}]}
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
    )

    first = service.run(limit=1)
    provider.responses["AAA"] = [{"timestamp": timestamp, "close": 150.0}]
    second = service.run(limit=1)

    assert first.observations_inserted == 1
    assert second.observations_inserted == 0
    assert second.observations_unchanged == 1
    rows = MarketObservationRepository(database=database).list_for_instrument(stock_id)
    assert rows[0]["close"] == 100.0


def test_backfill_continues_after_individual_failures_and_no_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, symbol="AAA", instrument_type="common_stock")
    _insert(instruments, symbol="BBB", instrument_type="unknown")
    _insert(instruments, symbol="CCC", instrument_type="common_stock")

    provider = FakeHistoryProvider(
        {
            "AAA": RuntimeError("provider failure"),
            "BBB": [],
            "CCC": [
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "close": 50.0,
                }
            ],
        }
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
    )

    report = service.run(limit=3)

    assert report.failed_count == 1
    assert report.no_history_count == 1
    assert report.persisted_instrument_count == 1
    assert report.observations_inserted == 1
    assert report.failures[0]["symbol"] == "AAA"
    assert report.to_api_dict()["status"] == "completed_with_failures"


def test_backfill_respects_limit_and_offset(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    for symbol in ("AAA", "BBB", "CCC"):
        _insert(instruments, symbol=symbol, instrument_type="common_stock")

    provider = FakeHistoryProvider(
        {
            "BBB": [
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "close": 100.0,
                }
            ]
        }
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
    )

    report = service.run(limit=1, offset=1)

    assert report.selected_count == 1
    assert provider.calls == ["BBB"]


def test_backfill_blocking_only_skips_instruments_with_valid_deep_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    observations = MarketObservationRepository(database=database)
    blocked_id = _insert(instruments, symbol="BLOCKED", instrument_type="common_stock")
    valid_id = _insert(instruments, symbol="VALID", instrument_type="common_stock")
    _insert(instruments, symbol="ETF1", instrument_type="etf")

    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    valid_history = [
        {
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "close": 100.0 + day,
        }
        for day in range(0, 366, 5)
    ]
    if valid_history[-1]["timestamp"] != (start + timedelta(days=365)).isoformat():
        valid_history.append(
            {
                "timestamp": (start + timedelta(days=365)).isoformat(),
                "close": 465.0,
            }
        )
    observations.save_many(
        instrument_id=valid_id,
        observations=valid_history,
        source_provider="yahoo_finance",
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    provider = FakeHistoryProvider(
        {
            "BLOCKED": [
                {
                    "timestamp": datetime(2025, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "close": 50.0,
                }
            ],
            "VALID": RuntimeError("VALID must not be requested"),
        }
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    )

    report = service.run(limit=10, blocking_only=True)

    assert blocked_id != valid_id
    assert report.selected_count == 1
    assert report.persisted_instrument_count == 1
    assert report.skipped_non_equity_count == 0
    assert report.selection_mode == "history_blockers"
    assert report.to_api_dict()["selectionMode"] == "history_blockers"
    assert provider.calls == ["BLOCKED"]
    assert provider.date_calls == [("BLOCKED", "2024-11-28", "2026-01-02")]
    assert report.effective_from_date == "2024-11-28"
    assert report.effective_to_date == "2026-01-02"
    assert report.history_window_auto_expanded is True
    assert report.to_api_dict()["historyWindow"] == {
        "fromDate": "2024-11-28",
        "toDate": "2026-01-02",
        "autoExpandedForBlockers": True,
    }


def test_blocking_backfill_anchors_automatic_lookback_to_explicit_to_date(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, symbol="BLOCKED", instrument_type="common_stock")
    provider = FakeHistoryProvider({"BLOCKED": []})
    service = MarketObservationBackfillService(database=database, history_provider=provider)

    report = service.run(limit=1, blocking_only=True, to_date="2026-06-30")

    assert provider.date_calls == [("BLOCKED", "2025-05-26", "2026-06-30")]
    assert report.history_window_auto_expanded is True


def test_blocking_backfill_never_overrides_explicit_from_date(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, symbol="BLOCKED", instrument_type="common_stock")
    provider = FakeHistoryProvider({"BLOCKED": []})
    service = MarketObservationBackfillService(database=database, history_provider=provider)

    report = service.run(
        limit=1,
        blocking_only=True,
        from_date="2020-01-01",
        to_date="2026-06-30",
    )

    assert provider.date_calls == [("BLOCKED", "2020-01-01", "2026-06-30")]
    assert report.history_window_auto_expanded is False

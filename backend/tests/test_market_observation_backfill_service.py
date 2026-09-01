from datetime import datetime, timezone
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

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(symbol)
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

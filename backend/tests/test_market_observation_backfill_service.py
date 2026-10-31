from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

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
                    "sourceProvider": "yahoo",
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
    assert rows[0]["source_provider"] == "yahoo"


def test_backfill_rejects_history_that_declares_different_provider(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    stock_id = _insert(instruments, symbol="AAA", instrument_type="common_stock")
    provider = FakeHistoryProvider(
        {
            "AAA": [
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "sourceProvider": "other_provider",
                    "close": 100.0,
                }
            ]
        }
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
    )

    report = service.run(limit=1)

    assert report.failed_count == 1
    assert report.persisted_instrument_count == 0
    assert report.observations_inserted == 0
    assert "procedencia" in report.failures[0]["error"]
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


def test_backfill_rejects_empty_declared_provider(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    stock_id = _insert(instruments, symbol="AAA", instrument_type="common_stock")
    provider = FakeHistoryProvider(
        {
            "AAA": [
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                    "sourceProvider": "   ",
                    "close": 100.0,
                }
            ]
        }
    )
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
    )

    report = service.run(limit=1)

    assert report.failed_count == 1
    assert report.observations_inserted == 0
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


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


@pytest.mark.parametrize("invalid_symbol", ["BBB", "  "])
def test_backfill_rejects_mismatched_declared_symbol_before_any_write(
    tmp_path: Path, invalid_symbol: str
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({
        "AAA": [
            {
                "symbol": "AAA",
                "sourceProvider": "yahoo",
                "timestamp": "2026-01-01T21:00:00+00:00",
                "close": 100.0,
            },
            {
                "symbol": invalid_symbol,
                "sourceProvider": "yahoo",
                "timestamp": "2026-01-02T21:00:00+00:00",
                "close": 101.0,
            },
        ]
    })

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=1)

    assert report.failed_count == 1
    assert report.persisted_instrument_count == 0
    assert report.observations_inserted == 0
    assert "símbolo declarado" in report.failures[0]["error"]
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


def test_backfill_accepts_matching_declared_symbol_case_insensitively(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({
        "AAA": [{
            "symbol": "aaa",
            "sourceProvider": "yahoo",
            "timestamp": "2026-01-02T21:00:00+00:00",
            "close": 100.0,
        }]
    })

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=1)

    assert report.failed_count == 0
    assert report.observations_inserted == 1
    assert len(MarketObservationRepository(database=database).list_for_instrument(stock_id)) == 1


@pytest.mark.parametrize(
    "invalid_provenance",
    [
        {"sourceProvider": "yahoo", "source_provider": "other_provider"},
        {"sourceProvider": None, "source_provider": "yahoo"},
        {"source_provider": "other_provider"},
        {"sourceProvider": "yahoo", "source_provider": "   "},
    ],
)
def test_backfill_rejects_conflicting_provenance_aliases_atomically(
    tmp_path: Path, invalid_provenance: dict[str, object]
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({
        "AAA": [
            {
                "symbol": "AAA",
                "sourceProvider": "yahoo",
                "timestamp": "2026-01-01T21:00:00+00:00",
                "close": 100.0,
            },
            {
                "symbol": "AAA",
                "timestamp": "2026-01-02T21:00:00+00:00",
                "close": 101.0,
                **invalid_provenance,
            },
        ]
    })

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=1)

    assert report.failed_count == 1
    assert report.observations_inserted == 0
    assert report.persisted_instrument_count == 0
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


def test_backfill_requires_explicit_provenance_for_secondary_provider(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({
        "AAA": [{
            "timestamp": "2026-01-02T21:00:00+00:00",
            "close": 100.0,
        }]
    })

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=1, source_provider="independent_secondary")

    assert report.failed_count == 1
    assert "procedencia" in report.failures[0]["error"]
    assert report.observations_inserted == 0
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


def test_backfill_rejects_adapter_relabel_before_fetch(tmp_path: Path) -> None:
    class NamedProvider(FakeHistoryProvider):
        PROVIDER_ID = "yahoo"

    database = _database(tmp_path)
    _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = NamedProvider({"AAA": []})
    service = MarketObservationBackfillService(
        database=database, history_provider=provider
    )

    with pytest.raises(ValueError, match="identidad del proveedor"):
        service.run(limit=1, source_provider="independent_secondary")
    assert provider.calls == []


def test_backfill_accepts_matching_dual_provenance_aliases(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({
        "AAA": [{
            "symbol": "AAA",
            "sourceProvider": "yahoo",
            "source_provider": "yahoo",
            "timestamp": "2026-01-02T21:00:00+00:00",
            "close": 100.0,
        }]
    })

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=1)

    assert report.failed_count == 0
    assert report.observations_inserted == 1
    assert len(MarketObservationRepository(database=database).list_for_instrument(stock_id)) == 1


@pytest.mark.parametrize(
    ("from_date", "to_date", "error"),
    [
        (None, "2026-10-26", "to_date no puede ser una fecha futura"),
        ("2026-10-26", None, "from_date no puede ser una fecha futura"),
        ("2026-01-03", "2026-01-02", "from_date no puede ser posterior"),
        ("20260102", "2026-01-03", "from_date debe tener formato"),
        (None, "2026-02-30", "to_date debe tener formato"),
    ],
)
def test_backfill_rejects_invalid_pit_windows_before_any_network_or_write(
    tmp_path: Path, from_date: str | None, to_date: str | None, error: str
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({"AAA": [{"timestamp": "2026-01-02T21:00:00+00:00", "close": 100.0}]})
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 10, 25),
    )

    with pytest.raises(ValueError, match=error):
        service.run(limit=1, from_date=from_date, to_date=to_date, blocking_only=True)

    assert provider.calls == []
    assert MarketObservationRepository(database=database).list_for_instrument(stock_id) == []


def test_historical_blocker_selection_uses_requested_pit_cutoff_not_today(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    stock_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA",
        instrument_type="common_stock",
    )
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    history = [
        {"timestamp": (start + timedelta(days=day)).isoformat(), "close": 100.0}
        for day in range(0, 366, 5)
    ]
    if history[-1]["timestamp"] != (start + timedelta(days=365)).isoformat():
        history.append({"timestamp": (start + timedelta(days=365)).isoformat(), "close": 100.0})
    MarketObservationRepository(database=database).save_many(
        instrument_id=stock_id,
        observations=history,
        source_provider="yahoo",
        retrieved_at=datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc),
    )
    provider = FakeHistoryProvider({"AAA": RuntimeError("No blocker at the requested cutoff")})
    service = MarketObservationBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 10, 25),
    )

    report = service.run(limit=10, blocking_only=True, to_date="2026-01-02")

    assert report.selected_count == 0
    assert report.failed_count == 0
    assert report.effective_to_date == "2026-01-02"
    assert provider.calls == []

def test_backfill_records_knowledge_time_after_each_provider_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slow multi-symbol requests must not backdate PIT knowledge to batch start."""
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    first_id = _insert(instruments, symbol="AAA", instrument_type="common_stock")
    second_id = _insert(instruments, symbol="BBB", instrument_type="common_stock")

    class ControlledDateTime(datetime):
        current = datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)

    class SlowProvider(FakeHistoryProvider):
        def get_history(self, symbol, from_date=None, to_date=None):
            ControlledDateTime.current += timedelta(minutes=1)
            return super().get_history(symbol, from_date, to_date)

    provider = SlowProvider({
        symbol: [{"timestamp": "2026-01-01T21:00:00+00:00", "close": 100.0}]
        for symbol in ("AAA", "BBB")
    })
    monkeypatch.setattr(
        "app.services.market_observation_backfill_service.datetime",
        ControlledDateTime,
    )

    report = MarketObservationBackfillService(
        database=database, history_provider=provider
    ).run(limit=2)

    assert report.failed_count == 0
    assert report.observations_inserted == 2
    observations = MarketObservationRepository(database=database)
    first = observations.list_for_instrument(first_id)[0]
    second = observations.list_for_instrument(second_id)[0]
    assert first["retrieved_at"] == "2026-01-02T20:01:00+00:00"
    assert second["retrieved_at"] == "2026-01-02T20:02:00+00:00"
    assert provider.calls == ["AAA", "BBB"]


def test_backfill_rejects_listing_mutation_during_provider_request(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA", instrument_type="common_stock",
    )

    class MutatingProvider(FakeHistoryProvider):
        def get_history(self, symbol, from_date=None, to_date=None):
            with database.connect() as connection:
                connection.execute(
                    "UPDATE instruments SET exchange_short_name = ? WHERE id = ?",
                    ("NYSE", instrument_id),
                )
            return [{"timestamp": "2026-01-02T21:00:00+00:00", "close": 100.0}]

    report = MarketObservationBackfillService(
        database=database, history_provider=MutatingProvider({}),
    ).run(limit=1)

    assert report.failed_count == 1
    assert "identidad" in report.failures[0]["error"]
    assert report.observations_inserted == 0
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_frozen_backfill_rejects_symbol_remap_before_network(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA", instrument_type="common_stock",
    )
    with database.connect() as connection:
        connection.execute("UPDATE instruments SET symbol = ? WHERE id = ?", ("ZZZ", instrument_id))
    provider = FakeHistoryProvider({"ZZZ": []})

    with pytest.raises(RuntimeError, match="identidad congelada"):
        MarketObservationBackfillService(
            database=database, history_provider=provider,
        ).run(
            limit=1, blocking_only=True, _instrument_ids=(instrument_id,),
            _expected_symbols=("AAA",),
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "bad_observation",
    [
        {"timestamp": "2025-12-31T21:00:00+00:00", "close": 99.0},
        {"timestamp": "2026-01-03T21:00:00+00:00", "close": 103.0},
        {"observed_at": "2026-01-02T21:00:00+00:00",
         "timestamp": "2026-01-03T21:00:00+00:00", "close": 103.0},
        {"timestamp": "2026-01-02T21:00:00", "close": 102.0},
    ],
)
def test_backfill_rejects_mixed_out_of_window_or_conflicting_provider_rows_atomically(
    tmp_path: Path, bad_observation: dict[str, object],
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database), symbol="AAA", instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({"AAA": [
        {"timestamp": "2026-01-01T21:00:00+00:00", "close": 101.0},
        bad_observation,
    ]})
    report = MarketObservationBackfillService(
        database=database, history_provider=provider,
        today_provider=lambda: date(2026, 1, 5),
    ).run(limit=1, from_date="2026-01-01", to_date="2026-01-02")

    assert provider.date_calls == [("AAA", "2026-01-01", "2026-01-02")]
    assert report.failed_count == 1
    assert report.persisted_instrument_count == 0
    assert report.observations_inserted == 0
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_backfill_explicit_start_is_bounded_to_today_and_rejects_future_response(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database), symbol="AAA", instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({"AAA": [
        {"timestamp": "2026-01-03T21:00:00+00:00", "close": 103.0},
    ]})
    report = MarketObservationBackfillService(
        database=database, history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=1, from_date="2026-01-01")

    assert provider.date_calls == [("AAA", "2026-01-01", "2026-01-02")]
    assert report.effective_to_date == "2026-01-02"
    assert report.failed_count == 1
    assert report.observations_inserted == 0
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_backfill_accepts_equivalent_timestamp_aliases_inside_pit_window(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database), symbol="AAA", instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({"AAA": [{
        "observed_at": "2026-01-02T21:00:00+00:00",
        "timestamp": "2026-01-02T16:00:00-05:00",
        "close": 102.0,
    }]})
    report = MarketObservationBackfillService(
        database=database, history_provider=provider,
        today_provider=lambda: date(2026, 1, 5),
    ).run(limit=1, from_date="2026-01-01", to_date="2026-01-02")

    assert report.failed_count == 0
    assert report.observations_inserted == 1
    assert len(MarketObservationRepository(database=database).list_for_instrument(instrument_id)) == 1


@pytest.mark.parametrize("future_field", ["timestamp", "observed_at"])
def test_backfill_rejects_future_instant_on_current_utc_day_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, future_field: str
) -> None:
    """Today's date is not sufficient: a later clock time is still lookahead."""
    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc)
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

    monkeypatch.setattr(
        "app.services.market_observation_backfill_service.datetime",
        ControlledDateTime,
    )
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA", instrument_type="common_stock",
    )
    provider = FakeHistoryProvider({"AAA": [
        {"timestamp": "2026-01-02T19:00:00+00:00", "close": 100.0},
        {future_field: "2026-01-02T21:00:00+00:00", "close": 101.0},
    ]})
    report = MarketObservationBackfillService(
        database=database, history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=1, from_date="2026-01-01", to_date="2026-01-02")

    assert provider.calls == ["AAA"]
    assert report.failed_count == 1
    assert report.observations_inserted == 0
    assert "ventana temporal" in report.failures[0]["error"]
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_backfill_uses_response_completion_not_request_start_for_same_day_pit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response available at 20:10 can legitimately contain a 20:05 event."""
    class ControlledDateTime(datetime):
        current = datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)

    class DelayedProvider(FakeHistoryProvider):
        def get_history(self, symbol, from_date=None, to_date=None):
            ControlledDateTime.current += timedelta(minutes=10)
            return super().get_history(symbol, from_date, to_date)

    monkeypatch.setattr(
        "app.services.market_observation_backfill_service.datetime",
        ControlledDateTime,
    )
    database = _database(tmp_path)
    instrument_id = _insert(
        InstrumentRepository(database=database),
        symbol="AAA", instrument_type="common_stock",
    )
    provider = DelayedProvider({"AAA": [
        {"timestamp": "2026-01-02T20:05:00+00:00", "close": 100.0},
    ]})
    report = MarketObservationBackfillService(
        database=database, history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=1, from_date="2026-01-01", to_date="2026-01-02")

    assert report.failed_count == 0
    assert report.observations_inserted == 1
    rows = MarketObservationRepository(database=database).list_for_instrument(instrument_id)
    assert len(rows) == 1
    assert rows[0]["retrieved_at"] == "2026-01-02T20:10:00+00:00"

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_ingestion_service import CorporateActionIngestionService


class FakeHistoryProvider:
    def __init__(self, observations: list[dict[str, object]]) -> None:
        self.observations = observations
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((symbol, from_date, to_date))
        return list(self.observations)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument_id(database: AthenaDatabase, symbol: str = "AAPL") -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name
            ) VALUES (?, ?, ?)
            """,
            (symbol, "Test Company", "NASDAQ"),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def _observation(
    *,
    timestamp: str,
    retrieved_at: str,
    dividend: float | None = None,
    split: float | None = None,
    symbol: str = "AAPL",
    provider: str = "yahoo",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "retrievedAt": retrieved_at,
        "sourceProvider": provider,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "adjustedClose": 100.5,
        "volume": 1_000_000.0,
        "dividend": dividend,
        "stockSplit": split,
    }


def test_ingest_history_persists_dividend_and_split_with_pit_provenance(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    retrieved_at = "2026-09-11T08:00:00+00:00"
    provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-08-01T00:00:00+00:00",
                retrieved_at=retrieved_at,
                dividend=0.25,
            ),
            _observation(
                timestamp="2026-08-15T00:00:00+00:00",
                retrieved_at=retrieved_at,
                split=4.0,
            ),
        ]
    )
    repository = CorporateActionRepository(database)
    service = CorporateActionIngestionService(
        market_provider=provider,
        repository=repository,
    )

    stats = service.ingest_history(
        instrument_id=instrument_id,
        symbol="aapl",
        from_date="2026-01-01",
        to_date="2026-09-10",
        dividend_currency="usd",
    )

    assert provider.calls == [("AAPL", "2026-01-01", "2026-09-10")]
    assert stats.history_observations == 2
    assert stats.actions_received == 2
    assert stats.inserted == 2
    assert stats.unchanged == 0
    assert stats.retrieval_batches == 1

    rows = repository.list_for_instrument(instrument_id)
    assert [row["action_type"] for row in rows] == ["dividend", "split"]
    assert rows[0]["cash_amount"] == 0.25
    assert rows[0]["currency"] == "USD"
    assert rows[0]["source_provider"] == "yahoo"
    assert datetime.fromisoformat(rows[0]["retrieved_at"]) >= datetime.fromisoformat(retrieved_at)
    assert rows[0]["capture_verified"] == 1
    assert rows[1]["retrieved_at"] == rows[0]["retrieved_at"]
    assert rows[1]["split_ratio"] == 4.0
    assert rows[1]["currency"] is None


def test_reingesting_same_provider_snapshot_is_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-08-01T00:00:00+00:00",
                retrieved_at="2026-09-11T08:00:00+00:00",
                dividend=0.25,
            )
        ]
    )
    repository = CorporateActionRepository(database)
    service = CorporateActionIngestionService(
        market_provider=provider,
        repository=repository,
    )

    first = service.ingest_history(
        instrument_id=instrument_id,
        symbol="AAPL",
        dividend_currency="USD",
    )
    second = service.ingest_history(
        instrument_id=instrument_id,
        symbol="AAPL",
        dividend_currency="USD",
    )

    assert first.inserted == 1
    assert first.unchanged == 0
    assert second.inserted == 0
    assert second.unchanged == 1
    assert len(repository.list_for_instrument(instrument_id)) == 1


def test_later_retrieval_remains_distinct_and_respects_knowledge_cutoff(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)

    first_provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-06-01T00:00:00+00:00",
                retrieved_at="2026-07-01T00:00:00+00:00",
                split=2.0,
            )
        ]
    )
    CorporateActionIngestionService(
        market_provider=first_provider,
        repository=repository,
        clock=lambda: datetime(2026, 9, 15, tzinfo=timezone.utc),
    ).ingest_history(instrument_id=instrument_id, symbol="AAPL")

    second_provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-06-01T00:00:00+00:00",
                retrieved_at="2026-09-01T00:00:00+00:00",
                split=3.0,
            )
        ]
    )
    CorporateActionIngestionService(
        market_provider=second_provider,
        repository=repository,
        clock=lambda: datetime(2026, 9, 20, tzinfo=timezone.utc),
    ).ingest_history(instrument_id=instrument_id, symbol="AAPL")

    before_discovery = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    after_first = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    after_second = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )

    assert before_discovery == []
    assert len(after_first) == 1
    assert len(after_second) == 2
    assert after_first[0]["retrieved_at"] == "2026-09-15T00:00:00+00:00"
    assert sorted(row["split_ratio"] for row in after_second) == [2.0, 3.0]


def test_ingestion_groups_actions_by_exact_provider_and_retrieval_time(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-08-01T00:00:00+00:00",
                retrieved_at="2026-09-10T08:00:00+00:00",
                dividend=0.10,
                provider="yahoo",
            ),
            _observation(
                timestamp="2026-08-02T00:00:00+00:00",
                retrieved_at="2026-09-11T08:00:00+00:00",
                dividend=0.20,
                provider="yahoo",
            ),
        ]
    )
    service = CorporateActionIngestionService(
        market_provider=provider,
        repository=CorporateActionRepository(database),
    )

    stats = service.ingest_history(
        instrument_id=instrument_id,
        symbol="AAPL",
        dividend_currency="USD",
    )

    assert stats.actions_received == 2
    assert stats.inserted == 2
    assert stats.retrieval_batches == 1


def test_empty_history_does_not_touch_repository(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    provider = FakeHistoryProvider([])
    repository = CorporateActionRepository(database)
    service = CorporateActionIngestionService(
        market_provider=provider,
        repository=repository,
    )

    stats = service.ingest_history(instrument_id=instrument_id, symbol="AAPL")

    assert stats.history_observations == 0
    assert stats.actions_received == 0
    assert stats.inserted == 0
    assert stats.unchanged == 0
    assert repository.list_for_instrument(instrument_id) == []


def test_ingestion_rejects_provider_symbol_mismatch_before_persistence(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-08-01T00:00:00+00:00",
                retrieved_at="2026-09-11T08:00:00+00:00",
                dividend=0.25,
                symbol="MSFT",
            )
        ]
    )
    service = CorporateActionIngestionService(
        market_provider=provider,
        repository=repository,
    )

    try:
        service.ingest_history(
            instrument_id=instrument_id,
            symbol="AAPL",
            dividend_currency="USD",
        )
    except ValueError as exc:
        assert "símbolo distinto" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo del símbolo incoherente.")

    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize("invalid_row", ["wrong_symbol", "wrong_provider"])
@pytest.mark.parametrize("include_valid_action", [False, True])
def test_ingestion_rejects_invalid_history_rows_even_without_actions(
    tmp_path: Path, invalid_row: str, include_valid_action: bool
) -> None:
    """No-action rows must not hide a wrong symbol or provider family."""
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    observations = []
    if include_valid_action:
        observations.append(
            _observation(
                timestamp="2026-08-01T00:00:00+00:00",
                retrieved_at="2026-09-11T08:00:00+00:00",
                dividend=0.25,
            )
        )
    observations.append(
        _observation(
            timestamp="2026-08-02T00:00:00+00:00",
            retrieved_at="2026-09-11T08:00:00+00:00",
            symbol="MSFT" if invalid_row == "wrong_symbol" else "AAPL",
            provider="other_provider" if invalid_row == "wrong_provider" else "yahoo",
        )
    )
    service = CorporateActionIngestionService(
        market_provider=FakeHistoryProvider(observations),
        repository=repository,
    )

    with pytest.raises(
        ValueError,
        match="símbolo distinto" if invalid_row == "wrong_symbol"
        else "provenance mismatch",
    ):
        service.ingest_history(
            instrument_id=instrument_id,
            symbol="AAPL",
            dividend_currency="USD",
            expected_source_provider="yahoo",
        )
    # Validate all history rows before saving any batch.
    assert repository.list_for_instrument(instrument_id) == []


def test_expected_provider_accepts_matching_empty_action_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    service = CorporateActionIngestionService(
        market_provider=FakeHistoryProvider(
            [_observation(
                timestamp="2026-08-02T00:00:00+00:00",
                retrieved_at="2026-09-11T08:00:00+00:00",
                provider="YAHOO",
                symbol="aapl",
            )]
        ),
        repository=CorporateActionRepository(database),
    )
    stats = service.ingest_history(
        instrument_id=instrument_id,
        symbol="AAPL",
        expected_source_provider="Yahoo",
    )
    assert stats.history_observations == 1
    assert stats.actions_received == 0
    assert stats.inserted == 0


@pytest.mark.parametrize("has_dividend", [False, True])
def test_ingestion_rejects_mismatched_instrument_id_before_provider_call(
    tmp_path: Path, has_dividend: bool
) -> None:
    database = _database(tmp_path)
    aapl_id = _instrument_id(database, "AAPL")
    repository = CorporateActionRepository(database)
    # The provider would correctly return MSFT, but the caller passed AAPL's ID.
    provider = FakeHistoryProvider(
        [_observation(
            timestamp="2026-08-01T00:00:00+00:00",
            retrieved_at="2026-09-11T08:00:00+00:00",
            symbol="MSFT",
            dividend=0.25 if has_dividend else None,
        )]
    )
    service = CorporateActionIngestionService(
        market_provider=provider, repository=repository
    )

    with pytest.raises(ValueError, match="instrument_id y symbol"):
        service.ingest_history(
            instrument_id=aapl_id,
            symbol="MSFT",
            dividend_currency="USD",
            expected_source_provider="yahoo",
        )

    assert provider.calls == []
    assert repository.list_for_instrument(aapl_id) == []


def test_ingestion_rejects_unknown_instrument_before_provider_call(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)
    provider = FakeHistoryProvider([])
    service = CorporateActionIngestionService(
        market_provider=provider, repository=repository
    )

    with pytest.raises(ValueError, match="instrument_id no corresponde"):
        service.ingest_history(instrument_id=999, symbol="AAPL")

    assert provider.calls == []
    assert repository.list_for_instrument(999) == []


def test_ingestion_accepts_case_insensitive_stored_instrument_symbol(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database, "aapl")
    repository = CorporateActionRepository(database)
    provider = FakeHistoryProvider(
        [_observation(
            timestamp="2026-08-01T00:00:00+00:00",
            retrieved_at="2026-09-11T08:00:00+00:00",
            dividend=0.25,
        )]
    )
    service = CorporateActionIngestionService(
        market_provider=provider, repository=repository
    )

    stats = service.ingest_history(
        instrument_id=instrument_id,
        symbol="AAPL",
        dividend_currency="USD",
    )

    assert stats.inserted == 1
    assert provider.calls == [("AAPL", None, None)]
    assert len(repository.list_for_instrument(instrument_id)) == 1



@pytest.mark.parametrize("extra_timestamp", [
    "2026-07-31T23:59:59+00:00",
    "2026-09-13T00:00:00+00:00",
    "2026-08-01T01:00:00+02:00",
    "not-a-timestamp",
    "2026-08-15T00:00:00",
])
@pytest.mark.parametrize("valid_first", [False, True])
def test_ingestion_rejects_out_of_window_or_invalid_observation_without_partial_write(
    tmp_path: Path, extra_timestamp: str, valid_first: bool,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    rows = [_observation(
        timestamp=extra_timestamp, retrieved_at="2026-09-15T12:00:00+00:00",
        dividend=0.50,
    )]
    if valid_first:
        rows.insert(0, _observation(
            timestamp="2026-08-15T00:00:00+00:00",
            retrieved_at="2026-09-15T12:00:00+00:00", dividend=0.25,
        ))
    provider = FakeHistoryProvider(rows)
    with pytest.raises(ValueError, match="ventana PIT|timestamp"):
        CorporateActionIngestionService(
            market_provider=provider, repository=repository,
        ).ingest_history(
            instrument_id=instrument_id, symbol="AAPL",
            from_date="2026-08-01", to_date="2026-09-12",
            dividend_currency="USD",
        )
    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize(("from_date", "to_date"), [
    ("2026-02-30", None),
    ("20260801", None),
    ("2026-09-12", "2026-09-11"),
    ("2026-08-01", "2099-01-01"),
])
def test_ingestion_rejects_invalid_windows_before_provider_call(
    tmp_path: Path, from_date: str, to_date: str | None,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    provider = FakeHistoryProvider([])
    with pytest.raises(ValueError):
        CorporateActionIngestionService(
            market_provider=provider,
            repository=CorporateActionRepository(database),
        ).ingest_history(
            instrument_id=instrument_id, symbol="AAPL",
            from_date=from_date, to_date=to_date,
        )
    assert provider.calls == []


def test_ingestion_caps_open_upper_window_and_rejects_future_provider_knowledge(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    provider = FakeHistoryProvider([_observation(
        timestamp="2099-01-01T00:00:00+00:00",
        retrieved_at="2099-01-02T00:00:00+00:00", dividend=0.25,
    )])
    with pytest.raises(ValueError, match="futuro|ventana PIT"):
        CorporateActionIngestionService(
            market_provider=provider, repository=repository,
        ).ingest_history(
            instrument_id=instrument_id, symbol="AAPL", from_date="2026-01-01",
        )
    assert provider.calls[0][2] == datetime.now(timezone.utc).date().isoformat()
    assert repository.list_for_instrument(instrument_id) == []


def test_ingestion_rejects_future_retrieval_even_for_past_economic_date(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    provider = FakeHistoryProvider([_observation(
        timestamp="2026-08-15T00:00:00+00:00",
        retrieved_at="2099-01-01T00:00:00+00:00", dividend=0.25,
    )])
    with pytest.raises(ValueError, match="conocimiento futuro"):
        CorporateActionIngestionService(
            market_provider=provider, repository=repository,
        ).ingest_history(instrument_id=instrument_id, symbol="AAPL")
    assert repository.list_for_instrument(instrument_id) == []




def test_ingestion_preserves_distinct_events_at_same_effective_and_retrieval_time(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    retrieved_at = "2026-09-11T08:00:00+00:00"
    provider = FakeHistoryProvider([
        _observation(
            timestamp="2026-08-01T00:00:00+00:00",
            retrieved_at=retrieved_at, dividend=0.25,
        ),
        _observation(
            timestamp="2026-08-01T00:00:00+00:00",
            retrieved_at=retrieved_at, dividend=0.30,
        ),
    ])
    service = CorporateActionIngestionService(
        market_provider=provider, repository=repository,
    )
    first = service.ingest_history(instrument_id=instrument_id, symbol="AAPL")
    second = service.ingest_history(instrument_id=instrument_id, symbol="AAPL")
    assert first.inserted == 2 and first.unchanged == 0
    assert second.inserted == 0 and second.unchanged == 2
    rows = repository.list_for_instrument(instrument_id)
    assert len(rows) == 2
    assert sorted(row["cash_amount"] for row in rows) == [0.25, 0.30]


def test_provider_backdating_cannot_make_a_dividend_visible_before_local_capture(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    capture = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider([_observation(
        timestamp="2026-08-15T00:00:00+00:00",
        retrieved_at="2026-08-16T00:00:00+00:00",
        dividend=0.25,
    )])
    service = CorporateActionIngestionService(
        market_provider=provider, repository=repository, clock=lambda: capture,
    )
    first = service.ingest_history(instrument_id=instrument_id, symbol="AAPL")
    replay = service.ingest_history(instrument_id=instrument_id, symbol="AAPL")
    assert first.inserted == 1 and replay.inserted == 0 and replay.unchanged == 1
    assert repository.list_for_instrument(
        instrument_id, knowledge_cutoff=datetime(2026, 9, 1, tzinfo=timezone.utc),
    ) == []
    rows = repository.list_for_instrument(instrument_id, knowledge_cutoff=capture)
    assert len(rows) == 1
    assert rows[0]["retrieved_at"] == capture.isoformat()
    assert rows[0]["capture_verified"] == 1


def test_legacy_provider_timestamp_cannot_deduplicate_new_local_capture(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = CorporateActionRepository(database)
    repository.save_many(
        instrument_id=instrument_id, source_provider="yahoo",
        retrieved_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        actions=[{
            "type": "split", "effectiveAt": "2026-08-15T00:00:00+00:00",
            "splitRatio": 4.0, "sourceTimestamp": "2026-08-15T00:00:00+00:00",
        }],
    )
    provider = FakeHistoryProvider([_observation(
        timestamp="2026-08-15T00:00:00+00:00",
        retrieved_at="2026-09-11T00:00:00+00:00", split=4.0,
    )])
    capture = datetime(2026, 10, 30, tzinfo=timezone.utc)
    result = CorporateActionIngestionService(
        market_provider=provider, repository=repository, clock=lambda: capture,
    ).ingest_history(instrument_id=instrument_id, symbol="AAPL")
    assert result.inserted == 1
    rows = repository.list_for_instrument(instrument_id)
    assert len(rows) == 2
    assert sorted(row["capture_verified"] for row in rows) == [0, 1]
    assert max(row["retrieved_at"] for row in rows) == capture.isoformat()

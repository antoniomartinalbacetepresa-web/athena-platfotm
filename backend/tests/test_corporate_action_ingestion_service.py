from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
    assert rows[0]["retrieved_at"] == retrieved_at
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
    ).ingest_history(instrument_id=instrument_id, symbol="AAPL")

    second_provider = FakeHistoryProvider(
        [
            _observation(
                timestamp="2026-06-01T00:00:00+00:00",
                retrieved_at="2026-09-01T00:00:00+00:00",
                split=2.0,
            )
        ]
    )
    CorporateActionIngestionService(
        market_provider=second_provider,
        repository=repository,
    ).ingest_history(instrument_id=instrument_id, symbol="AAPL")

    before_discovery = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    after_first = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    after_second = repository.list_for_instrument(
        instrument_id,
        knowledge_cutoff=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert before_discovery == []
    assert len(after_first) == 1
    assert len(after_second) == 2
    assert after_first[0]["retrieved_at"] == "2026-07-01T00:00:00+00:00"


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
    assert stats.retrieval_batches == 2


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

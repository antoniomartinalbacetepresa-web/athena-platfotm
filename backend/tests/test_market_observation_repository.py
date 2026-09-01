from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument_id(database: AthenaDatabase) -> int:
    return InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
        }
    )


def test_market_observation_repository_preserves_first_point_in_time_value(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = MarketObservationRepository(database=database)
    observed_at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)

    first = repository.save_many(
        instrument_id=instrument_id,
        observations=[
            {
                "timestamp": observed_at.isoformat(),
                "open": 99.0,
                "high": 102.0,
                "low": 98.0,
                "close": 100.0,
                "adjustedClose": 100.0,
                "volume": 1000,
            }
        ],
        source_provider="yahoo_finance",
        retrieved_at=observed_at + timedelta(minutes=1),
    )

    second = repository.save_many(
        instrument_id=instrument_id,
        observations=[
            {
                "timestamp": observed_at.isoformat(),
                "close": 150.0,
                "adjustedClose": 150.0,
            }
        ],
        source_provider="yahoo_finance",
        retrieved_at=observed_at + timedelta(days=30),
    )

    rows = repository.list_for_instrument(
        instrument_id,
        source_provider="yahoo_finance",
    )

    assert first.inserted == 1
    assert first.unchanged == 0
    assert second.inserted == 0
    assert second.unchanged == 1
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(100.0)
    assert rows[0]["adjusted_close"] == pytest.approx(100.0)


def test_market_observation_repository_keeps_sources_separate(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = MarketObservationRepository(database=database)
    observed_at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)

    for provider, price in (("source_a", 100.0), ("source_b", 101.0)):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[
                {
                    "timestamp": observed_at.isoformat(),
                    "close": price,
                }
            ],
            source_provider=provider,
            retrieved_at=observed_at + timedelta(minutes=1),
        )

    rows = repository.list_for_instrument(instrument_id)

    assert len(rows) == 2
    assert {row["source_provider"] for row in rows} == {"source_a", "source_b"}
    assert {row["close"] for row in rows} == {100.0, 101.0}


def test_market_observation_repository_requires_timezone_aware_observation(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = MarketObservationRepository(database=database)

    with pytest.raises(ValueError, match="zona horaria"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[
                {
                    "timestamp": datetime(2026, 1, 2, 21, 0).isoformat(),
                    "close": 100.0,
                }
            ],
            source_provider="yahoo_finance",
            retrieved_at=datetime(2026, 1, 2, 21, 1, tzinfo=timezone.utc),
        )


def test_market_observation_repository_reports_inserted_and_unchanged(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument_id(database)
    repository = MarketObservationRepository(database=database)
    base = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)

    stats = repository.save_many(
        instrument_id=instrument_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {
                "timestamp": (base + timedelta(days=1)).isoformat(),
                "close": 101.0,
            },
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=2),
    )

    assert stats.received == 2
    assert stats.inserted == 2
    assert stats.unchanged == 0

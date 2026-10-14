from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_observation_coverage_service import MarketObservationCoverageService


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase, symbol: str = "AAA") -> int:
    return InstrumentRepository(database=database).upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "TEST",
            "instrumentType": "common_stock",
        }
    )


def _history(start: datetime, end_day: int, *, step_days: int = 5) -> list[dict[str, object]]:
    return [
        {
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "close": 100.0 + day / 100.0,
        }
        for day in range(0, end_day + 1, step_days)
    ]


def test_market_history_excludes_observations_after_pit_cutoff(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    repository = MarketObservationRepository(database=database)
    cutoff = datetime(2026, 1, 10, 21, 0, tzinfo=timezone.utc)
    before = cutoff - timedelta(days=1)
    after = cutoff + timedelta(days=1)
    repository.save_many(
        instrument_id=instrument_id,
        observations=[
            {"timestamp": before.isoformat(), "close": 100.0},
            {"timestamp": after.isoformat(), "close": 999.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=after + timedelta(days=1),
    )

    report = MarketObservationCoverageService(database=database).get_report(as_of=cutoff)

    assert report.observation_count == 1
    assert report.latest_observed_at == before.isoformat()
    assert report.to_api_dict()["pointInTimeCutoffApplied"] is True
    assert report.to_api_dict()["asOf"] == cutoff.isoformat()


def test_deep_but_stale_segment_is_not_current_at_pit_cutoff(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    start = datetime(2024, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations = _history(start, 365)
    observations.append(
        {"timestamp": (start + timedelta(days=365)).isoformat(), "close": 110.0}
    )
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=observations,
        source_provider="yahoo_finance",
        retrieved_at=start + timedelta(days=366),
    )
    cutoff = datetime(2026, 1, 15, 21, 0, tzinfo=timezone.utc)

    report = MarketObservationCoverageService(database=database).get_report(as_of=cutoff)

    assert report.deep_history_instrument_count == 1
    assert report.deep_history_coverage == 1.0
    assert report.current_deep_history_instrument_count == 0
    assert report.current_deep_history_coverage == 0.0
    assert report.current_history_depth_ready is False


def test_deep_segment_reaching_cutoff_is_current(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    cutoff = datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    start = cutoff - timedelta(days=365)
    observations = _history(start, 365)
    observations.append({"timestamp": cutoff.isoformat(), "close": 110.0})
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=observations,
        source_provider="yahoo_finance",
        retrieved_at=cutoff,
    )

    report = MarketObservationCoverageService(database=database).get_report(as_of=cutoff)

    assert report.deep_history_instrument_count == 1
    assert report.current_deep_history_instrument_count == 1
    assert report.current_deep_history_coverage == 1.0
    assert report.current_history_depth_ready is True


def test_market_history_rejects_naive_pit_cutoff(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="zona horaria"):
        MarketObservationCoverageService(database=database).get_report(
            as_of=datetime(2026, 1, 1, 21, 0)
        )

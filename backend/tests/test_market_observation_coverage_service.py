from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_observation_coverage_service import (
    MarketObservationCoverageService,
)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _insert_instrument(
    repository: InstrumentRepository,
    symbol: str,
    *,
    instrument_type: str = "common_stock",
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


def test_market_observation_coverage_reports_overall_and_sources(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    first_id = _insert_instrument(instruments, "AAA")
    second_id = _insert_instrument(instruments, "BBB")
    _insert_instrument(instruments, "CCC")

    observations = MarketObservationRepository(database=database)
    base = datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(
        instrument_id=first_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {"timestamp": (base + timedelta(days=1)).isoformat(), "close": 101.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=2),
    )
    observations.save_many(
        instrument_id=second_id,
        observations=[
            {"timestamp": (base + timedelta(days=2)).isoformat(), "close": 50.0},
        ],
        source_provider="secondary_source",
        retrieved_at=base + timedelta(days=3),
    )

    report = MarketObservationCoverageService(database=database).get_report()

    assert report.active_instrument_count == 3
    assert report.history_eligible_instrument_count == 3
    assert report.covered_instrument_count == 2
    assert report.instrument_coverage == pytest.approx(2 / 3)
    assert report.deep_history_instrument_count == 0
    assert report.deep_history_coverage == 0.0
    assert report.history_depth_ready is False
    assert report.observation_count == 3
    assert report.earliest_observed_at == base.isoformat()
    assert report.latest_observed_at == (base + timedelta(days=2)).isoformat()
    assert report.by_source["yahoo_finance"]["observationCount"] == 2
    assert report.by_source["secondary_source"]["coveredInstrumentCount"] == 1


def test_market_observation_coverage_is_zero_for_empty_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert_instrument(instruments, "AAA")

    report = MarketObservationCoverageService(database=database).get_report()

    assert report.active_instrument_count == 1
    assert report.history_eligible_instrument_count == 1
    assert report.covered_instrument_count == 0
    assert report.instrument_coverage == 0.0
    assert report.deep_history_coverage == 0.0
    assert report.history_depth_ready is False
    assert report.observation_count == 0
    assert report.earliest_observed_at is None
    assert report.latest_observed_at is None
    assert report.by_source == {}


def test_history_depth_uses_365_day_span_and_explicit_coverage_threshold(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    first_id = _insert_instrument(instruments, "AAA")
    second_id = _insert_instrument(instruments, "BBB")
    third_id = _insert_instrument(instruments, "CCC")

    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    for instrument_id in (first_id, second_id):
        observations.save_many(
            instrument_id=instrument_id,
            observations=[
                {"timestamp": base.isoformat(), "close": 100.0},
                {
                    "timestamp": (base + timedelta(days=365)).isoformat(),
                    "close": 110.0,
                },
            ],
            source_provider="yahoo_finance",
            retrieved_at=base + timedelta(days=366),
        )
    observations.save_many(
        instrument_id=third_id,
        observations=[{"timestamp": base.isoformat(), "close": 90.0}],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=1),
    )

    report = MarketObservationCoverageService(database=database).get_report()

    assert report.minimum_history_days == 365
    assert report.minimum_deep_history_coverage == pytest.approx(0.30)
    assert report.deep_history_instrument_count == 2
    assert report.deep_history_coverage == pytest.approx(2 / 3)
    assert report.history_depth_ready is True


def test_etfs_and_funds_do_not_dilute_history_coverage_denominator(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    equity_id = _insert_instrument(instruments, "AAA")
    _insert_instrument(instruments, "ETF1", instrument_type="etf")
    _insert_instrument(instruments, "FUND1", instrument_type="fund")

    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(
        instrument_id=equity_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {
                "timestamp": (base + timedelta(days=365)).isoformat(),
                "close": 110.0,
            },
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=366),
    )

    report = MarketObservationCoverageService(database=database).get_report()

    assert report.active_instrument_count == 3
    assert report.history_eligible_instrument_count == 1
    assert report.covered_instrument_count == 1
    assert report.instrument_coverage == 1.0
    assert report.deep_history_coverage == 1.0
    assert report.history_depth_ready is True

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


def _insert_instrument(repository: InstrumentRepository, symbol: str, *, instrument_type: str = "common_stock") -> int:
    return repository.upsert({
        "symbol": symbol,
        "companyName": symbol,
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": symbol,
        "instrumentType": instrument_type,
    })


def _continuous_history(base: datetime, *, days: int = 365, step_days: int = 5) -> list[dict[str, object]]:
    points = [
        {"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100}
        for day in range(0, days + 1, step_days)
    ]
    if (days % step_days) != 0:
        points.append({"timestamp": (base + timedelta(days=days)).isoformat(), "close": 110.0})
    return points


def test_market_observation_coverage_reports_overall_and_sources(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    first_id = _insert_instrument(instruments, "AAA")
    second_id = _insert_instrument(instruments, "BBB")
    _insert_instrument(instruments, "CCC")
    observations = MarketObservationRepository(database=database)
    base = datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(instrument_id=first_id, observations=[
        {"timestamp": base.isoformat(), "close": 100.0},
        {"timestamp": (base + timedelta(days=1)).isoformat(), "close": 101.0},
    ], source_provider="yahoo_finance", retrieved_at=base + timedelta(days=2))
    observations.save_many(instrument_id=second_id, observations=[
        {"timestamp": (base + timedelta(days=2)).isoformat(), "close": 50.0},
    ], source_provider="secondary_source", retrieved_at=base + timedelta(days=3))
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.active_instrument_count == 3
    assert report.history_eligible_instrument_count == 3
    assert report.covered_instrument_count == 2
    assert report.instrument_coverage == pytest.approx(2 / 3)
    assert report.deep_history_instrument_count == 0
    assert report.history_depth_ready is False
    assert report.observation_count == 3
    assert report.earliest_observed_at == base.isoformat()
    assert report.latest_observed_at == (base + timedelta(days=2)).isoformat()
    assert report.by_source["yahoo_finance"]["observationCount"] == 2
    assert report.by_source["secondary_source"]["coveredInstrumentCount"] == 1


def test_market_observation_coverage_is_zero_for_empty_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_instrument(InstrumentRepository(database=database), "AAA")
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.active_instrument_count == 1
    assert report.covered_instrument_count == 0
    assert report.deep_history_coverage == 0.0
    assert report.history_depth_ready is False
    assert report.by_source == {}


def test_history_depth_requires_365_day_span_and_bounded_source_gaps(tmp_path: Path) -> None:
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
            observations=_continuous_history(base),
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
    assert report.maximum_source_gap_days == 7
    assert report.minimum_deep_history_coverage == pytest.approx(0.30)
    assert report.deep_history_instrument_count == 2
    assert report.deep_history_coverage == pytest.approx(2 / 3)
    assert report.history_depth_ready is True
    assert report.to_api_dict()["sourceContinuityRequired"] is True
    assert report.to_api_dict()["maximumSourceGapDays"] == 7


def test_history_depth_rejects_sparse_same_source_span(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(
        instrument_id=instrument_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {"timestamp": (base + timedelta(days=365)).isoformat(), "close": 110.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=366),
    )
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.covered_instrument_count == 1
    assert report.deep_history_instrument_count == 0
    assert report.deep_history_coverage == 0.0
    assert report.history_depth_ready is False


def test_history_depth_accepts_valid_segment_after_older_source_gap(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    old_point = datetime(2023, 1, 1, 21, 0, tzinfo=timezone.utc)
    segment_start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": old_point.isoformat(), "close": 80.0}],
        source_provider="yahoo_finance",
        retrieved_at=old_point + timedelta(days=1),
    )
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(segment_start),
        source_provider="yahoo_finance",
        retrieved_at=segment_start + timedelta(days=366),
    )

    report = MarketObservationCoverageService(database=database).get_report()

    assert report.deep_history_instrument_count == 1
    assert report.deep_history_coverage == 1.0
    assert report.history_depth_ready is True


def test_history_depth_does_not_stitch_different_sources(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(instrument_id=instrument_id, observations=[{"timestamp": base.isoformat(), "close": 100.0}], source_provider="source_a", retrieved_at=base + timedelta(days=1))
    observations.save_many(instrument_id=instrument_id, observations=[{"timestamp": (base + timedelta(days=365)).isoformat(), "close": 110.0}], source_provider="source_b", retrieved_at=base + timedelta(days=366))
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.deep_history_instrument_count == 0
    assert report.history_depth_ready is False


def test_history_depth_counts_instrument_once_when_multiple_sources_are_deep(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    for source in ("source_a", "source_b"):
        observations.save_many(
            instrument_id=instrument_id,
            observations=_continuous_history(base),
            source_provider=source,
            retrieved_at=base + timedelta(days=366),
        )
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.deep_history_instrument_count == 1
    assert report.deep_history_coverage == 1.0
    assert report.history_depth_ready is True


def test_etfs_and_funds_do_not_dilute_history_coverage_denominator(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    equity_id = _insert_instrument(instruments, "AAA")
    _insert_instrument(instruments, "ETF1", instrument_type="etf")
    _insert_instrument(instruments, "FUND1", instrument_type="fund")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=equity_id,
        observations=_continuous_history(base),
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=366),
    )
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.active_instrument_count == 3
    assert report.history_eligible_instrument_count == 1
    assert report.instrument_coverage == 1.0
    assert report.deep_history_coverage == 1.0
    assert report.history_depth_ready is True


def test_history_depth_rejects_non_positive_gap_threshold(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketObservationCoverageService(database=database, maximum_source_gap_days=0)

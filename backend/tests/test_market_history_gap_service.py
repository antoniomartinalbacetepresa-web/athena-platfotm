from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService


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


def _continuous_history(base: datetime, *, days: int = 365) -> list[dict[str, object]]:
    return [
        {
            "timestamp": (base + timedelta(days=day)).isoformat(),
            "close": 100.0 + day / 100,
        }
        for day in range(0, days + 1, 5)
    ]


def test_history_gap_report_classifies_actionable_blockers(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    no_history_id = _insert_instrument(instruments, "AAA")
    short_id = _insert_instrument(instruments, "BBB")
    discontinuous_id = _insert_instrument(instruments, "CCC")
    deep_id = _insert_instrument(instruments, "DDD")
    _insert_instrument(instruments, "ETF1", instrument_type="etf")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)

    observations.save_many(
        instrument_id=short_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {"timestamp": (base + timedelta(days=100)).isoformat(), "close": 101.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=101),
    )
    observations.save_many(
        instrument_id=discontinuous_id,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {"timestamp": (base + timedelta(days=365)).isoformat(), "close": 110.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=366),
    )
    observations.save_many(
        instrument_id=deep_id,
        observations=_continuous_history(base),
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=366),
    )

    report = MarketHistoryGapService(database=database).get_report()

    assert report.total_blocking_count == 3
    assert report.no_observations_count == 1
    assert report.insufficient_span_count == 1
    assert report.discontinuous_source_count == 1
    assert [item.symbol for item in report.items] == ["AAA", "BBB", "CCC"]
    assert report.items[0].instrument_id == no_history_id
    assert report.items[0].best_source_provider is None
    assert report.items[1].reason == "insufficient_span"
    assert report.items[1].best_source_provider == "yahoo"
    assert report.items[1].best_history_span_days == pytest.approx(100.0)
    assert report.items[2].reason == "discontinuous_source"
    assert report.items[2].best_source_provider == "yahoo"
    assert report.items[2].best_history_span_days == pytest.approx(365.0)
    assert report.items[2].best_maximum_gap_days == pytest.approx(365.0)
    assert deep_id not in {item.instrument_id for item in report.items}

    payload = report.to_api_dict()
    assert payload["productionEvidenceClaimed"] is False
    assert payload["minimumHistoryDays"] == 365
    assert payload["maximumSourceGapDays"] == 7


def test_history_gap_report_accepts_any_single_deep_source_without_stitching(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)

    observations.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": base.isoformat(), "close": 100.0}],
        source_provider="source_a",
        retrieved_at=base + timedelta(days=1),
    )
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="source_b",
        retrieved_at=base + timedelta(days=366),
    )

    report = MarketHistoryGapService(database=database).get_report()
    assert report.total_blocking_count == 0
    assert report.items == ()


def test_history_gap_report_treats_yahoo_legacy_alias_as_same_provider(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    legacy = [
        {"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100}
        for day in range(0, 181, 5)
    ]
    canonical = [
        {"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100}
        for day in range(185, 366, 5)
    ]
    observations.save_many(
        instrument_id=instrument_id,
        observations=legacy,
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=181),
    )
    observations.save_many(
        instrument_id=instrument_id,
        observations=canonical,
        source_provider="yahoo",
        retrieved_at=base + timedelta(days=366),
    )

    report = MarketHistoryGapService(database=database).get_report()

    assert report.total_blocking_count == 0
    assert report.items == ()


def test_history_gap_report_clears_old_gap_when_later_segment_is_deep(tmp_path: Path) -> None:
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

    report = MarketHistoryGapService(database=database).get_report()

    assert report.total_blocking_count == 0
    assert report.discontinuous_source_count == 0
    assert report.items == ()


def test_history_gap_report_paginates_without_changing_totals(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    for symbol in ("AAA", "BBB", "CCC"):
        _insert_instrument(instruments, symbol)

    report = MarketHistoryGapService(database=database).get_report(limit=1, offset=1)
    assert report.total_blocking_count == 3
    assert len(report.items) == 1
    assert report.items[0].symbol == "BBB"


def test_history_gap_report_rejects_invalid_pagination_and_thresholds(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="minimum_history_days"):
        MarketHistoryGapService(database=database, minimum_history_days=0)
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketHistoryGapService(database=database, maximum_source_gap_days=0)

    service = MarketHistoryGapService(database=database)
    with pytest.raises(ValueError, match="limit"):
        service.get_report(limit=0)
    with pytest.raises(ValueError, match="limit"):
        service.get_report(limit=1001)
    with pytest.raises(ValueError, match="offset"):
        service.get_report(offset=-1)

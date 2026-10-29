from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _insert_instrument(repository: InstrumentRepository, symbol: str, *, instrument_type: str = "common_stock") -> int:
    return repository.upsert({"symbol": symbol, "companyName": symbol, "country": "United States", "regionKey": "america", "exchangeShortName": symbol, "instrumentType": instrument_type})


def _continuous_history(base: datetime, *, days: int = 365) -> list[dict[str, object]]:
    return [{"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100} for day in range(0, days + 1, 5)]


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
    observations.save_many(instrument_id=short_id, observations=[{"timestamp": base.isoformat(), "close": 100.0}, {"timestamp": (base + timedelta(days=100)).isoformat(), "close": 101.0}], source_provider="yahoo_finance", retrieved_at=base + timedelta(days=101))
    observations.save_many(instrument_id=discontinuous_id, observations=[{"timestamp": base.isoformat(), "close": 100.0}, {"timestamp": (base + timedelta(days=365)).isoformat(), "close": 110.0}], source_provider="yahoo_finance", retrieved_at=base + timedelta(days=366))
    observations.save_many(instrument_id=deep_id, observations=_continuous_history(base), source_provider="yahoo_finance", retrieved_at=base + timedelta(days=366))
    report = MarketHistoryGapService(database=database).get_report(as_of=base + timedelta(days=366))
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
    assert "MarketObservationCoverageService" in payload["warning"]


def test_history_gap_report_accepts_any_single_deep_source_without_stitching(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(instrument_id=instrument_id, observations=[{"timestamp": base.isoformat(), "close": 100.0}], source_provider="source_a", retrieved_at=base + timedelta(days=1))
    observations.save_many(instrument_id=instrument_id, observations=_continuous_history(base), source_provider="source_b", retrieved_at=base + timedelta(days=366))
    report = MarketHistoryGapService(database=database).get_report(as_of=base + timedelta(days=366))
    assert report.total_blocking_count == 0
    assert report.items == ()


def test_history_gap_report_treats_yahoo_legacy_alias_as_same_provider(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    legacy = [{"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100} for day in range(0, 181, 5)]
    canonical = [{"timestamp": (base + timedelta(days=day)).isoformat(), "close": 100.0 + day / 100} for day in range(185, 366, 5)]
    observations.save_many(instrument_id=instrument_id, observations=legacy, source_provider="yahoo_finance", retrieved_at=base + timedelta(days=181))
    observations.save_many(instrument_id=instrument_id, observations=canonical, source_provider="yahoo", retrieved_at=base + timedelta(days=366))
    report = MarketHistoryGapService(database=database).get_report(as_of=base + timedelta(days=366))
    assert report.total_blocking_count == 0
    assert report.items == ()


def test_history_gap_report_clears_old_gap_when_later_segment_is_deep(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    observations = MarketObservationRepository(database=database)
    old_point = datetime(2023, 1, 1, 21, 0, tzinfo=timezone.utc)
    segment_start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations.save_many(instrument_id=instrument_id, observations=[{"timestamp": old_point.isoformat(), "close": 80.0}], source_provider="yahoo_finance", retrieved_at=old_point + timedelta(days=1))
    observations.save_many(instrument_id=instrument_id, observations=_continuous_history(segment_start), source_provider="yahoo_finance", retrieved_at=segment_start + timedelta(days=366))
    report = MarketHistoryGapService(database=database).get_report(as_of=segment_start + timedelta(days=366))
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
        MarketHistoryGapService(database=database, minimum_history_days=364)
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


@pytest.mark.parametrize("gap_days", [-1, 0, 0.5, 8, 365, True])
def test_gap_diagnostic_cannot_weaken_continuity_acceptance(
    tmp_path: Path, gap_days: object,
) -> None:
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketHistoryGapService(
            database=_database(tmp_path), maximum_source_gap_days=gap_days,
        )


def test_gap_diagnostic_allows_stricter_continuity(tmp_path: Path) -> None:
    service = MarketHistoryGapService(
        database=_database(tmp_path),
        minimum_history_days=400,
        maximum_source_gap_days=5,
    )
    report = service.get_report()
    assert report.minimum_history_days == 400
    assert report.maximum_source_gap_days == 5
    assert report.total_blocking_count == 0


def test_gap_report_rejects_history_retrieved_after_pit_cutoff(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    final_observation = base + timedelta(days=365)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=final_observation + timedelta(days=1),
    )
    service = MarketHistoryGapService(database=database)

    before = service.get_report(as_of=final_observation + timedelta(hours=2))
    assert before.total_blocking_count == 1
    assert before.no_observations_count == 1
    assert before.items[0].reason == "no_observations"
    assert before.items[0].source_count == 0
    assert before.to_api_dict()["pointInTimeCutoffApplied"] is True
    assert before.to_api_dict()["productionEvidenceClaimed"] is False

    after = service.get_report(as_of=final_observation + timedelta(days=2))
    assert after.total_blocking_count == 0
    assert after.items == ()
    assert after.as_of != before.as_of


def test_gap_report_pit_excludes_future_observations_and_naive_cutoff(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "AAA")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations = MarketObservationRepository(database=database)
    observations.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": base.isoformat(), "close": 100.0}],
        source_provider="yahoo_finance",
        retrieved_at=base + timedelta(days=1),
    )
    future = base + timedelta(days=365)
    observations.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": future.isoformat(), "close": 120.0}],
        source_provider="yahoo",
        retrieved_at=future + timedelta(days=1),
    )
    service = MarketHistoryGapService(database=database)
    cutoff = base + timedelta(days=2)
    report = service.get_report(as_of=cutoff.astimezone(timezone(timedelta(hours=2))))
    assert report.total_blocking_count == 1
    assert report.insufficient_span_count == 1
    assert report.discontinuous_source_count == 0
    assert report.items[0].best_source_provider == "yahoo"
    assert report.items[0].best_history_span_days == pytest.approx(0.0)
    assert report.to_api_dict()["asOf"] == cutoff.isoformat()
    with pytest.raises(ValueError, match="as_of"):
        service.get_report(as_of=cutoff.replace(tzinfo=None))


def test_gap_diagnostics_use_absolute_instants_for_legacy_offset_rows(
    tmp_path: Path,
) -> None:
    """Lexical ISO ordering must not manufacture gaps in continuous history."""

    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "OFFSET")
    base = datetime(2025, 1, 1, 23, 0, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base) + [
            {"timestamp": (base + timedelta(hours=2)).isoformat(), "close": 101.0},
        ],
        source_provider="yahoo",
        retrieved_at=base + timedelta(days=366),
    )
    # Legacy persisted ISO strings may use offsets even though new writes normalize.
    with database.connect() as connection:
        for instant, offset in (
            (base, timedelta(hours=14)),
            (base + timedelta(hours=2), -timedelta(hours=12)),
        ):
            connection.execute(
                "UPDATE market_observations SET observed_at = ? "
                "WHERE instrument_id = ? AND observed_at = ?",
                (
                    instant.astimezone(timezone(offset)).isoformat(),
                    instrument_id,
                    instant.isoformat(),
                ),
            )

    report = MarketHistoryGapService(database=database).get_report(
        as_of=base + timedelta(days=366)
    )
    assert report.total_blocking_count == 0
    assert report.items == ()
    assert report.to_api_dict()["productionEvidenceClaimed"] is False


def test_stale_deep_history_is_an_actionable_pit_blocker(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "STALE")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations = MarketObservationRepository(database=database)
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=base + timedelta(days=366),
    )
    service = MarketHistoryGapService(database=database)

    current = service.get_report(as_of=base + timedelta(days=372))
    assert current.total_blocking_count == 0
    assert current.stale_source_count == 0

    stale = service.get_report(as_of=base + timedelta(days=373))
    assert stale.total_blocking_count == 1
    assert stale.stale_source_count == 1
    assert stale.items[0].reason == "stale_source"
    assert stale.items[0].instrument_id == instrument_id
    assert stale.items[0].best_source_provider == "yahoo"
    assert stale.to_api_dict()["blockingByReason"]["stale_source"] == 1
    assert stale.to_api_dict()["productionEvidenceClaimed"] is False


def test_stale_primary_does_not_block_current_independent_deep_source(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "FRESH")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    observations = MarketObservationRepository(database=database)
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="primary",
        retrieved_at=base + timedelta(days=366),
    )
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base + timedelta(days=20)),
        source_provider="secondary",
        retrieved_at=base + timedelta(days=386),
    )
    report = MarketHistoryGapService(database=database).get_report(
        as_of=base + timedelta(days=386)
    )
    assert report.total_blocking_count == 0
    assert report.stale_source_count == 0
    assert report.items == ()


@pytest.mark.parametrize("age_days,expected_blockers", [(372, 0), (373, 1)])
def test_gap_and_coverage_agree_on_current_pit_depth(
    tmp_path: Path, age_days: int, expected_blockers: int
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "CONSISTENT")
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=base + timedelta(days=366),
    )
    cutoff = base + timedelta(days=age_days)
    coverage = MarketObservationCoverageService(database=database).get_report(as_of=cutoff)
    gaps = MarketHistoryGapService(database=database).get_report(as_of=cutoff)

    assert coverage.history_eligible_instrument_count == 1
    assert coverage.deep_history_instrument_count == 1
    assert gaps.total_blocking_count == expected_blockers
    assert gaps.stale_source_count == expected_blockers
    assert coverage.current_deep_history_instrument_count == 1 - expected_blockers
    assert coverage.current_deep_history_instrument_count + gaps.total_blocking_count == 1


def test_legacy_retrieval_before_observation_cannot_complete_365_days(
    tmp_path: Path,
) -> None:
    """A predated last observation must not turn 360 days into 365 PIT days."""
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "LEGACY")
    base = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    last = base + timedelta(days=365)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=last + timedelta(days=1),
    )
    with database.connect() as connection:
        changed = connection.execute(
            "UPDATE market_observations SET retrieved_at = ? "
            "WHERE instrument_id = ? AND observed_at = ?",
            ((last - timedelta(days=1)).isoformat(), instrument_id, last.isoformat()),
        )
        assert changed.rowcount == 1

    cutoff = last + timedelta(days=2)
    coverage = MarketObservationCoverageService(database=database).get_report(as_of=cutoff)
    gaps = MarketHistoryGapService(database=database).get_report(as_of=cutoff)
    assert coverage.observation_count == 73
    assert coverage.deep_history_instrument_count == 0
    assert coverage.current_deep_history_instrument_count == 0
    assert coverage.current_history_depth_ready is False
    assert coverage.by_source["yahoo"]["observationCount"] == 73
    assert gaps.total_blocking_count == 1
    assert gaps.insufficient_span_count == 1
    assert gaps.items[0].reason == "insufficient_span"
    assert gaps.items[0].best_history_span_days == pytest.approx(360.0)
    assert gaps.to_api_dict()["productionEvidenceClaimed"] is False

@pytest.mark.parametrize("legacy_provider", [
    "", "fmp", "FinancialModelingPrep", "F-M-P",
    "F\tM\tP", "yahoo\n", "yahoo\x00fmp", "yahoo\x7f", "yahoo\u200b",
])
def test_legacy_forbidden_provenance_is_a_history_gap(
    tmp_path: Path, legacy_provider: str
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "LEGACYFMP")
    base = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=base + timedelta(days=366),
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_observations SET source_provider = ? WHERE instrument_id = ?",
            (legacy_provider, instrument_id),
        )
    report = MarketHistoryGapService(database=database).get_report(
        as_of=base + timedelta(days=366)
    )
    assert report.total_blocking_count == 1
    assert report.no_observations_count == 1
    assert report.items[0].reason == "no_observations"
    assert report.items[0].best_source_provider is None
    assert report.to_api_dict()["productionEvidenceClaimed"] is False
    # Legacy rows must not inflate either the gap or coverage diagnostic.
    coverage = MarketObservationCoverageService(database=database).get_report(
        as_of=base + timedelta(days=366)
    )
    assert coverage.observation_count == 0
    assert coverage.current_deep_history_instrument_count == 0
    assert coverage.by_source == {}
    assert coverage.to_api_dict()["productionCoverageClaimed"] is False

def test_future_source_timestamp_remains_blocked_in_gap_diagnostics(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "FUTURESRC")
    base = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    retrieved = base + timedelta(days=366)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=retrieved,
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_observations SET source_timestamp = ? WHERE instrument_id = ?",
            ((retrieved + timedelta(days=1)).isoformat(), instrument_id),
        )
    report = MarketHistoryGapService(database=database).get_report(
        as_of=retrieved + timedelta(days=2)
    )
    assert report.total_blocking_count == 1
    assert report.no_observations_count == 1
    assert report.items[0].reason == "no_observations"
    assert report.to_api_dict()["productionEvidenceClaimed"] is False


def test_price_history_acceptance_excludes_priceless_and_corrupt_legacy_rows(
    tmp_path: Path,
) -> None:
    """A 365-day timestamp series is not price coverage without valid closes."""
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    no_price_id = _insert_instrument(instruments, "NOPRICE")
    damaged_id = _insert_instrument(instruments, "DAMAGED")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    cutoff = base + timedelta(days=366)
    observations.save_many(
        instrument_id=no_price_id,
        observations=[
            {"timestamp": (base + timedelta(days=day)).isoformat(), "volume": 100}
            for day in range(0, 366, 5)
        ],
        source_provider="yahoo",
        retrieved_at=cutoff,
    )
    observations.save_many(
        instrument_id=damaged_id,
        observations=_continuous_history(base),
        source_provider="yahoo",
        retrieved_at=cutoff,
    )
    coverage_service = MarketObservationCoverageService(database=database)
    gap_service = MarketHistoryGapService(database=database)

    initial_coverage = coverage_service.get_report(as_of=cutoff)
    initial_gaps = gap_service.get_report(as_of=cutoff)
    assert initial_coverage.history_eligible_instrument_count == 2
    assert initial_coverage.covered_instrument_count == 1
    assert initial_coverage.current_deep_history_instrument_count == 1
    assert initial_gaps.no_observations_count == 1
    assert initial_gaps.items[0].symbol == "NOPRICE"

    # Legacy imports may predate today's positive-price validation.
    # A single invalid price must break the continuous seven-day segment.
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_observations SET close = -1 "
            "WHERE instrument_id = ? AND observed_at = ?",
            (damaged_id, (base + timedelta(days=180)).isoformat()),
        )
    coverage = coverage_service.get_report(as_of=cutoff)
    gaps = gap_service.get_report(as_of=cutoff)
    assert coverage.observation_count == len(_continuous_history(base)) - 1
    assert coverage.covered_instrument_count == 1
    assert coverage.current_deep_history_instrument_count == 0
    assert coverage.current_history_depth_ready is False
    assert gaps.total_blocking_count == 2
    assert gaps.no_observations_count == 1
    assert gaps.discontinuous_source_count == 1
    assert [item.symbol for item in gaps.items] == ["NOPRICE", "DAMAGED"]
    assert gaps.total_blocking_count + coverage.current_deep_history_instrument_count == 2
    assert coverage.to_api_dict()["positiveFiniteCloseRequired"] is True
    assert gaps.to_api_dict()["positiveFiniteCloseRequired"] is True

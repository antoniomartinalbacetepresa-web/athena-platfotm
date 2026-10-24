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
    assert report.by_source["yahoo"]["observationCount"] == 2
    assert "yahoo_finance" not in report.by_source
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


def test_history_depth_requires_full_eligible_universe_by_default(tmp_path: Path) -> None:
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
    assert report.minimum_deep_history_coverage == 1.0
    assert report.deep_history_instrument_count == 2
    assert report.deep_history_coverage == pytest.approx(2 / 3)
    assert report.history_depth_ready is False
    payload = report.to_api_dict()
    assert payload["sourceContinuityRequired"] is True
    assert payload["maximumSourceGapDays"] == 7
    assert payload["productionCoverageClaimed"] is False


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


def test_history_depth_preserves_continuity_across_yahoo_alias_transition(tmp_path: Path) -> None:
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
    report = MarketObservationCoverageService(database=database).get_report()
    assert report.deep_history_instrument_count == 1
    assert report.deep_history_coverage == 1.0
    assert report.by_source["yahoo"]["observationCount"] == len(legacy) + len(canonical)
    assert "yahoo_finance" not in report.by_source


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


def test_history_depth_can_be_stricter_but_not_invalid(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="minimum_deep_history_coverage"):
        MarketObservationCoverageService(database=database, minimum_deep_history_coverage=1.01)


def test_history_depth_rejects_non_positive_gap_threshold(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketObservationCoverageService(database=database, maximum_source_gap_days=0)


@pytest.mark.parametrize("days", [0, 30, 364, True, 365.5])
def test_history_coverage_rejects_weakened_depth_requirement(
    tmp_path: Path, days: object,
) -> None:
    with pytest.raises(ValueError, match="minimum_history_days"):
        MarketObservationCoverageService(
            database=_database(tmp_path), minimum_history_days=days,
        )


@pytest.mark.parametrize("coverage", [0.0, 0.5, 0.999, True, float("nan")])
def test_history_coverage_rejects_less_than_full_eligible_universe(
    tmp_path: Path, coverage: object,
) -> None:
    with pytest.raises(ValueError, match="minimum_deep_history_coverage"):
        MarketObservationCoverageService(
            database=_database(tmp_path), minimum_deep_history_coverage=coverage,
        )


@pytest.mark.parametrize("gap_days", [-1, 0, 0.5, 8, 365, True])
def test_history_coverage_rejects_relaxed_or_fractional_gap(
    tmp_path: Path, gap_days: object,
) -> None:
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketObservationCoverageService(
            database=_database(tmp_path), maximum_source_gap_days=gap_days,
        )


def test_history_coverage_allows_stricter_thresholds(tmp_path: Path) -> None:
    service = MarketObservationCoverageService(
        database=_database(tmp_path),
        minimum_history_days=400,
        minimum_deep_history_coverage=1.0,
        maximum_source_gap_days=5,
    )
    report = service.get_report()
    assert report.minimum_history_days == 400
    assert report.minimum_deep_history_coverage == 1.0
    assert report.maximum_source_gap_days == 5
    assert report.history_depth_ready is False


def test_coverage_as_of_excludes_late_discovered_observations_everywhere(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    known_id = _insert_instrument(instruments, "KNOWN")
    late_id = _insert_instrument(instruments, "LATE")
    observations = MarketObservationRepository(database=database)
    observed_at = datetime(2026, 1, 1, 21, 0, tzinfo=timezone.utc)
    cutoff = observed_at + timedelta(days=2)

    observations.save_many(
        instrument_id=known_id,
        observations=[{"timestamp": observed_at.isoformat(), "close": 100.0}],
        source_provider="source_known",
        retrieved_at=observed_at + timedelta(days=1),
    )
    observations.save_many(
        instrument_id=late_id,
        observations=[{"timestamp": observed_at.isoformat(), "close": 50.0}],
        source_provider="source_late",
        retrieved_at=observed_at + timedelta(days=3),
    )

    report = MarketObservationCoverageService(database=database).get_report(
        as_of=cutoff
    )

    assert report.active_instrument_count == 2
    assert report.history_eligible_instrument_count == 2
    assert report.observation_count == 1
    assert report.covered_instrument_count == 1
    assert report.earliest_observed_at == observed_at.isoformat()
    assert report.latest_observed_at == observed_at.isoformat()
    assert "source_known" in report.by_source
    assert "source_late" not in report.by_source
    assert report.to_api_dict()["pointInTimeCutoffApplied"] is True
    assert report.to_api_dict()["productionCoverageClaimed"] is False


def test_deep_coverage_cannot_use_history_retrieved_after_pit_cutoff(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _insert_instrument(
        InstrumentRepository(database=database), "AAA"
    )
    observations = MarketObservationRepository(database=database)
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    last_observation = start + timedelta(days=365)
    retrieved_at = last_observation + timedelta(days=1)
    observations.save_many(
        instrument_id=instrument_id,
        observations=_continuous_history(start),
        source_provider="yahoo",
        retrieved_at=retrieved_at,
    )
    service = MarketObservationCoverageService(database=database)

    before = service.get_report(as_of=last_observation + timedelta(hours=2))
    assert before.observation_count == 0
    assert before.covered_instrument_count == 0
    assert before.deep_history_instrument_count == 0
    assert before.current_deep_history_instrument_count == 0
    assert before.history_depth_ready is False
    assert before.current_history_depth_ready is False
    assert before.by_source == {}

    after = service.get_report(as_of=last_observation + timedelta(days=2))
    assert after.covered_instrument_count == 1
    assert after.deep_history_instrument_count == 1
    assert after.current_deep_history_instrument_count == 1
    assert after.history_depth_ready is True
    assert after.current_history_depth_ready is True


def test_coverage_depth_uses_absolute_instants_for_legacy_offset_rows(
    tmp_path: Path,
) -> None:
    """Offset spelling must not reduce measured 365-day history depth."""

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

    report = MarketObservationCoverageService(database=database).get_report(
        as_of=base + timedelta(days=366)
    )
    assert report.deep_history_instrument_count == 1
    assert report.current_deep_history_instrument_count == 1
    assert report.current_history_depth_ready is True
    assert report.to_api_dict()["productionCoverageClaimed"] is False


def test_coverage_boundaries_order_legacy_offset_rows_by_absolute_instant(
    tmp_path: Path,
) -> None:
    """Overall and per-source boundaries must not sort ISO offset strings lexically."""
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "OFFSET")
    first = datetime(2025, 1, 1, 23, 0, tzinfo=timezone.utc)
    last = first + timedelta(hours=2)
    retrieved = first + timedelta(hours=3)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=[
            {"timestamp": first.isoformat(), "close": 100.0},
            {"timestamp": last.isoformat(), "close": 101.0},
        ],
        source_provider="yahoo_finance",
        retrieved_at=retrieved,
    )
    earliest_spelling = first.astimezone(timezone(timedelta(hours=14))).isoformat()
    latest_spelling = last.astimezone(timezone(-timedelta(hours=12))).isoformat()
    with database.connect() as connection:
        for instant, spelling in (
            (first, earliest_spelling),
            (last, latest_spelling),
        ):
            connection.execute(
                "UPDATE market_observations SET observed_at = ? "
                "WHERE instrument_id = ? AND observed_at = ?",
                (spelling, instrument_id, instant.isoformat()),
            )

    report = MarketObservationCoverageService(database=database).get_report(
        as_of=retrieved + timedelta(hours=1)
    )
    assert report.observation_count == 2
    assert report.earliest_observed_at == earliest_spelling
    assert report.latest_observed_at == latest_spelling
    assert report.by_source["yahoo"]["earliestObservedAt"] == earliest_spelling
    assert report.by_source["yahoo"]["latestObservedAt"] == latest_spelling
    assert report.to_api_dict()["productionCoverageClaimed"] is False

    before_retrieval = MarketObservationCoverageService(database=database).get_report(
        as_of=first + timedelta(hours=2)
    )
    assert before_retrieval.observation_count == 0
    assert before_retrieval.earliest_observed_at is None
    assert before_retrieval.latest_observed_at is None
    assert before_retrieval.by_source == {}


def test_legacy_retrieval_before_observation_is_not_pit_evidence(tmp_path: Path) -> None:
    """Malformed legacy timestamps must never count as known market history."""
    database = _database(tmp_path)
    instrument_id = _insert_instrument(InstrumentRepository(database=database), "LEGACY")
    observed = datetime(2025, 1, 1, 21, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": observed.isoformat(), "close": 100.0}],
        source_provider="yahoo",
        retrieved_at=observed + timedelta(days=1),
    )
    # Simulate an old imported row violating the repository's write-time invariant.
    with database.connect() as connection:
        changed = connection.execute(
            "UPDATE market_observations SET retrieved_at = ? "
            "WHERE instrument_id = ? AND observed_at = ?",
            ((observed - timedelta(days=1)).isoformat(), instrument_id, observed.isoformat()),
        )
        assert changed.rowcount == 1

    report = MarketObservationCoverageService(database=database).get_report(
        as_of=observed + timedelta(days=2)
    )
    assert report.history_eligible_instrument_count == 1
    assert report.observation_count == 0
    assert report.covered_instrument_count == 0
    assert report.deep_history_instrument_count == 0
    assert report.current_deep_history_instrument_count == 0
    assert report.by_source == {}
    assert report.to_api_dict()["productionCoverageClaimed"] is False

@pytest.mark.parametrize("legacy_provider", ["", "fmp", "FinancialModelingPrep", "F-M-P"])
def test_legacy_forbidden_provenance_cannot_claim_historical_coverage(
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
    report = MarketObservationCoverageService(database=database).get_report(
        as_of=base + timedelta(days=366)
    )
    assert report.history_eligible_instrument_count == 1
    assert report.observation_count == 0
    assert report.covered_instrument_count == 0
    assert report.deep_history_instrument_count == 0
    assert report.current_deep_history_instrument_count == 0
    assert report.by_source == {}
    assert report.to_api_dict()["productionCoverageClaimed"] is False

def test_future_source_timestamp_cannot_count_as_pit_coverage(tmp_path: Path) -> None:
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
    report = MarketObservationCoverageService(database=database).get_report(
        as_of=retrieved + timedelta(days=2)
    )
    assert report.observation_count == 0
    assert report.current_deep_history_instrument_count == 0
    assert report.to_api_dict()["productionCoverageClaimed"] is False

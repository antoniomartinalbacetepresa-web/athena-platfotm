from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository
from app.services.recommendation_shadow_outcome_service import (
    RecommendationShadowOutcomeService,
)


CUT = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
DUE = CUT + timedelta(days=7)
AS_OF = CUT + timedelta(days=8)


def _setup(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    asset_id = instruments.upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
            "country": "United States",
            "regionKey": "america",
        }
    )
    benchmark_id = instruments.upsert(
        {
            "symbol": "SPY",
            "companyName": "SPDR S&P 500 ETF Trust",
            "exchangeShortName": "ARCX",
            "instrumentType": "etf",
            "country": "United States",
            "regionKey": "america",
        }
    )
    repository = RecommendationShadowRepository(database=database)
    snapshot_id = repository.create_snapshot(
        instrument_id=asset_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version="shadow-evidence-v2",
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot={"productionEligible": False},
        benchmark_symbol="SPY",
    )
    return database, repository, snapshot_id, asset_id, benchmark_id


def _insert_observation(database, instrument_id, observed_at, price, provider="test"):
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id, observed_at, close, source_provider, retrieved_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                observed_at.isoformat(),
                price,
                provider,
                (observed_at + timedelta(minutes=1)).isoformat(),
            ),
        )


def test_declared_benchmark_must_resolve_before_outcome_is_persisted(tmp_path) -> None:
    database, repository, snapshot_id, asset_id, _ = _setup(tmp_path)
    _insert_observation(database, asset_id, DUE + timedelta(hours=1), 110.0)

    result = RecommendationShadowOutcomeService(database=database).evaluate_snapshot(
        snapshot_id=snapshot_id,
        as_of=AS_OF,
        horizons=(7,),
    )

    assert result["evaluated"] == []
    assert result["missingBenchmarkHorizons"] == [
        {
            "horizonDays": 7,
            "benchmarkSymbol": "SPY",
            "benchmarkStatus": "benchmark_entry_price_missing",
        }
    ]
    assert repository.list_outcomes(snapshot_id) == []


def test_resolved_frozen_benchmark_is_persisted_with_exact_observation_provenance(
    tmp_path,
) -> None:
    database, repository, snapshot_id, asset_id, benchmark_id = _setup(tmp_path)
    asset_exit = DUE + timedelta(hours=1)
    benchmark_entry = CUT + timedelta(hours=1)
    benchmark_exit = DUE + timedelta(hours=2)
    _insert_observation(database, asset_id, asset_exit, 110.0, "asset_feed")
    _insert_observation(database, benchmark_id, benchmark_entry, 400.0, "benchmark_feed")
    _insert_observation(database, benchmark_id, benchmark_exit, 420.0, "benchmark_feed")

    result = RecommendationShadowOutcomeService(database=database).evaluate_snapshot(
        snapshot_id=snapshot_id,
        as_of=AS_OF,
        horizons=(7,),
    )

    assert len(result["evaluated"]) == 1
    item = result["evaluated"][0]
    assert item["realizedReturn"] == pytest.approx(0.10)
    assert item["benchmarkReturn"] == pytest.approx(0.05)
    assert item["excessReturn"] == pytest.approx(0.05)
    evidence = item["benchmarkEvidence"]
    assert evidence["benchmarkSymbol"] == "SPY"
    assert evidence["benchmarkInstrumentId"] == benchmark_id
    assert evidence["entryPrice"] == pytest.approx(400.0)
    assert evidence["exitPrice"] == pytest.approx(420.0)
    assert evidence["entrySourceProvider"] == "benchmark_feed"
    assert evidence["exitSourceProvider"] == "benchmark_feed"

    rows = repository.list_outcomes(snapshot_id)
    assert len(rows) == 1
    stored = rows[0]
    assert stored["benchmark_return"] == pytest.approx(0.05)
    assert stored["excess_return"] == pytest.approx(0.05)
    assert stored["benchmark_evidence"]["benchmarkInstrumentId"] == benchmark_id
    assert stored["benchmark_evidence"]["exitObservedAt"] == benchmark_exit.isoformat()

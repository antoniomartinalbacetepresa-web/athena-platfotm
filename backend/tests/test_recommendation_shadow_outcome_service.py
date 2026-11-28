from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository
from app.services.recommendation_shadow_outcome_service import (
    RecommendationShadowOutcomeService,
)


CUT = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)


def _setup(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
            "country": "United States",
            "regionKey": "america",
        }
    )
    repository = RecommendationShadowRepository(database=database)
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot={"productionEligible": False},
    )
    return database, repository, snapshot_id, instrument_id


def test_shadow_outcomes_evaluate_matured_horizons_without_action_labels(tmp_path) -> None:
    database, repository, snapshot_id, instrument_id = _setup(tmp_path)
    day7 = CUT + timedelta(days=7, hours=1)
    day30 = CUT + timedelta(days=30, hours=1)
    as_of = CUT + timedelta(days=31)
    with database.connect() as connection:
        for observed, price in ((day7, 110.0), (day30, 120.0)):
            connection.execute(
                """
                INSERT INTO market_observations (
                    instrument_id, observed_at, close, source_provider, retrieved_at
                ) VALUES (?, ?, ?, 'test_prices', ?)
                """,
                (
                    instrument_id,
                    observed.isoformat(),
                    price,
                    (observed + timedelta(minutes=1)).isoformat(),
                ),
            )

    result = RecommendationShadowOutcomeService(database=database).evaluate_snapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
    )

    assert result["advisoryStatus"] == "no_advice"
    assert [item["horizonDays"] for item in result["evaluated"]] == [7, 30]
    assert result["evaluated"][0]["realizedReturn"] == pytest.approx(0.10)
    assert result["evaluated"][1]["realizedReturn"] == pytest.approx(0.20)
    assert result["pendingHorizons"] == [90, 180, 365]
    rows = repository.list_outcomes(snapshot_id)
    assert [row["horizon_days"] for row in rows] == [7, 30]
    for row in rows:
        assert "action" not in row
        assert "conviction" not in row


def test_shadow_outcome_ignores_backfill_retrieved_after_as_of(tmp_path) -> None:
    database, _, snapshot_id, instrument_id = _setup(tmp_path)
    due_observed = CUT + timedelta(days=7, hours=1)
    as_of = CUT + timedelta(days=8)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id, observed_at, close, source_provider, retrieved_at
            ) VALUES (?, ?, 110.0, 'known', ?)
            """,
            (
                instrument_id,
                due_observed.isoformat(),
                (due_observed + timedelta(minutes=1)).isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id, observed_at, close, source_provider, retrieved_at
            ) VALUES (?, ?, 9999.0, 'future_backfill', ?)
            """,
            (
                instrument_id,
                due_observed.isoformat(),
                (as_of + timedelta(days=1)).isoformat(),
            ),
        )

    result = RecommendationShadowOutcomeService(database=database).evaluate_snapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
        horizons=(7,),
    )

    assert len(result["evaluated"]) == 1
    assert result["evaluated"][0]["exitPrice"] == pytest.approx(110.0)
    assert result["evaluated"][0]["exitPrice"] != pytest.approx(9999.0)


def test_shadow_outcome_is_idempotent_per_horizon(tmp_path) -> None:
    database, _, snapshot_id, instrument_id = _setup(tmp_path)
    observed = CUT + timedelta(days=7, hours=1)
    as_of = CUT + timedelta(days=8)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id, observed_at, close, source_provider, retrieved_at
            ) VALUES (?, ?, 105.0, 'test', ?)
            """,
            (
                instrument_id,
                observed.isoformat(),
                observed.isoformat(),
            ),
        )

    service = RecommendationShadowOutcomeService(database=database)
    first = service.evaluate_snapshot(snapshot_id=snapshot_id, as_of=as_of, horizons=(7,))
    second = service.evaluate_snapshot(snapshot_id=snapshot_id, as_of=as_of, horizons=(7,))

    assert len(first["evaluated"]) == 1
    assert second["evaluated"] == []
    assert second["alreadyEvaluatedHorizons"] == [7]

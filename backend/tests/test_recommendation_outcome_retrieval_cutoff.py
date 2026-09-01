from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_outcome_evaluation_service import (
    RecommendationOutcomeEvaluationService,
)


def test_outcome_evaluator_ignores_future_backfill_and_persists_retrieval_time(
    tmp_path,
) -> None:
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
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = RecommendationHistoryRepository(
        database=database
    ).create_recommendation(
        symbol="AAPL",
        action="buy",
        score=80.0,
        conviction=0.8,
        horizon_days=90,
        generated_at=generated,
        data_cutoff_at=generated - timedelta(minutes=1),
        model_version="test-existing-evaluator",
        rationale={},
        input_snapshot={},
        instrument_id=instrument_id,
    )
    due = generated + timedelta(days=7)
    as_of = generated + timedelta(days=8)
    entry_observed = generated + timedelta(hours=1)
    exit_observed = due + timedelta(hours=1)
    exit_retrieved = exit_observed + timedelta(minutes=1)

    with database.connect() as connection:
        for observed_at, price, retrieved_at in (
            (entry_observed, 100.0, entry_observed + timedelta(minutes=1)),
            (exit_observed, 110.0, exit_retrieved),
            (exit_observed, 9999.0, as_of + timedelta(days=1)),
        ):
            connection.execute(
                """
                INSERT INTO market_observations (
                    instrument_id, observed_at, close, source_provider, retrieved_at
                ) VALUES (?, ?, ?, 'test', ?)
                """,
                (
                    instrument_id,
                    observed_at.isoformat(),
                    price,
                    retrieved_at.isoformat(),
                ),
            )

    report = RecommendationOutcomeEvaluationService(database=database).evaluate_due(
        as_of=as_of
    )

    assert report.evaluated_count == 1
    evaluated = report.evaluated[0]
    assert evaluated["entryPrice"] == pytest.approx(100.0)
    assert evaluated["exitPrice"] == pytest.approx(110.0)
    assert evaluated["realizedReturn"] == pytest.approx(0.10)
    assert evaluated["exitRetrievedAt"] == exit_retrieved.isoformat()
    assert evaluated["exitPrice"] != pytest.approx(9999.0)

    outcomes = RecommendationHistoryRepository(database=database).list_outcomes(
        recommendation_id
    )
    assert len(outcomes) == 1
    assert outcomes[0]["source_timestamp"] == exit_retrieved.isoformat()

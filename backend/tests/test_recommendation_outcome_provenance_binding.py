from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_history_repository import RecommendationHistoryRepository
from app.services.recommendation_outcome_evaluation_service import (
    RecommendationOutcomeEvaluationService,
)


def test_outcome_persists_exact_exit_provider_not_caller_label(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
            "marketCap": 1000.0,
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
        model_version="athena-v1",
        rationale={},
        input_snapshot={},
        instrument_id=instrument_id,
    )

    entry_observed = generated + timedelta(hours=1)
    exit_observed = generated + timedelta(days=7, hours=1)
    entry_retrieved = entry_observed + timedelta(minutes=3)
    exit_retrieved = exit_observed + timedelta(minutes=4)
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO market_observations (
                instrument_id, observed_at, close, source_provider, retrieved_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    instrument_id,
                    entry_observed.isoformat(),
                    100.0,
                    "entry_feed",
                    entry_retrieved.isoformat(),
                ),
                (
                    instrument_id,
                    exit_observed.isoformat(),
                    110.0,
                    "verified_exit_feed",
                    exit_retrieved.isoformat(),
                ),
            ),
        )

    report = RecommendationOutcomeEvaluationService(database=database).evaluate_due(
        as_of=generated + timedelta(days=8),
        source_provider="caller_supplied_spoof",
    )

    assert report.evaluated_count == 1
    evaluated = report.evaluated[0]
    assert evaluated["entrySourceProvider"] == "entry_feed"
    assert evaluated["exitSourceProvider"] == "verified_exit_feed"
    assert report.to_api_dict()["outcomeSourcePolicy"] == (
        "persist_exact_exit_observation_provider_and_retrieval_timestamp"
    )

    outcomes = RecommendationHistoryRepository(database=database).list_outcomes(
        recommendation_id
    )
    assert len(outcomes) == 1
    assert outcomes[0]["source_provider"] == "verified_exit_feed"
    assert outcomes[0]["source_timestamp"] == exit_retrieved.isoformat()

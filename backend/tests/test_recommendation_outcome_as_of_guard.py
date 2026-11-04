from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_outcome_evaluation_service import (
    RecommendationOutcomeEvaluationService,
)


def test_outcome_evaluator_never_uses_price_after_as_of(tmp_path: Path) -> None:
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
        }
    )
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    RecommendationHistoryRepository(database=database).create_recommendation(
        symbol="AAPL",
        action="buy",
        score=80,
        conviction=0.8,
        horizon_days=90,
        generated_at=generated,
        data_cutoff_at=generated,
        model_version="v1",
        rationale={},
        input_snapshot={},
        instrument_id=instrument_id,
    )

    with database.connect() as connection:
        for observed_at, close in (
            (generated + timedelta(hours=1), 100.0),
            (generated + timedelta(days=10), 120.0),
        ):
            connection.execute(
                """
                INSERT INTO market_observations (
                    instrument_id,
                    observed_at,
                    close,
                    source_provider,
                    retrieved_at
                ) VALUES (?, ?, ?, 'test_prices', ?)
                """,
                (
                    instrument_id,
                    observed_at.isoformat(),
                    close,
                    observed_at.isoformat(),
                ),
            )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(
        as_of=generated + timedelta(days=8),
    )

    assert report.due_count == 1
    assert report.evaluated_count == 0
    assert report.skipped_missing_exit_price == 1
    assert report.to_api_dict()["temporalWindowPolicy"] == (
        "entry_before_due_exit_not_after_as_of"
    )

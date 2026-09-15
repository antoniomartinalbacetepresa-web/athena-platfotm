from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import RecommendationHistoryRepository
from app.services.recommendation_performance_service import RecommendationPerformanceService


def _record(database: AthenaDatabase, *, model_version: str) -> int:
    history = RecommendationHistoryRepository(database=database)
    generated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recommendation_id = history.create_recommendation(
        symbol="AAPL",
        action="buy",
        score=80.0,
        conviction=0.9,
        horizon_days=30,
        generated_at=generated_at,
        data_cutoff_at=generated_at,
        model_version=model_version,
        rationale={"reason": "test"},
        input_snapshot={"source": "fixture"},
    )
    history.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=30,
        evaluated_at=generated_at + timedelta(days=31),
        entry_price=100.0,
        exit_price=110.0,
        source_provider="test",
    )
    return recommendation_id


def test_performance_fails_closed_when_outcome_horizon_differs_from_frozen_recommendation(tmp_path) -> None:
    database = AthenaDatabase(path=tmp_path / "athena.db")
    recommendation_id = _record(database, model_version="v1")
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET horizon_days = 31 WHERE recommendation_id = ?",
            (recommendation_id,),
        )

    with pytest.raises(RuntimeError, match="horizon_days inconsistente"):
        RecommendationPerformanceService(database=database).get_report(model_version="v1")


def test_performance_horizon_integrity_is_scoped_to_requested_model_version(tmp_path) -> None:
    database = AthenaDatabase(path=tmp_path / "athena.db")
    corrupted_id = _record(database, model_version="legacy")
    _record(database, model_version="current")
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET horizon_days = 31 WHERE recommendation_id = ?",
            (corrupted_id,),
        )

    report = RecommendationPerformanceService(database=database).get_report(model_version="current")
    assert report.sample_count == 1
    assert report.horizon_days is None

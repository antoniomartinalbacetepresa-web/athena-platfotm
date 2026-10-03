from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import RecommendationHistoryRepository
from app.services.recommendation_calibration_service import RecommendationCalibrationService


def test_calibration_rejects_outcome_whose_horizon_differs_from_frozen_recommendation(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = history.create_recommendation(
        symbol="AAPL",
        action="buy",
        score=75,
        conviction=0.9,
        horizon_days=30,
        generated_at=generated,
        data_cutoff_at=generated,
        model_version="v1",
        rationale={},
        input_snapshot={},
    )
    history.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=30,
        evaluated_at=generated + timedelta(days=30),
        entry_price=100.0,
        exit_price=110.0,
        source_provider="test",
    )

    # Simulate legacy/corrupt persisted evidence bypassing repository validation.
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET horizon_days = 31 WHERE recommendation_id = ?",
            (recommendation_id,),
        )

    with pytest.raises(RuntimeError, match="recomendación congeló 30"):
        RecommendationCalibrationService(database=database).get_report(model_version="v1")


def test_horizon_integrity_check_respects_requested_model_scope(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    bad_id = history.create_recommendation(
        symbol="BAD",
        action="buy",
        score=70,
        conviction=0.8,
        horizon_days=30,
        generated_at=generated,
        data_cutoff_at=generated,
        model_version="legacy",
        rationale={},
        input_snapshot={},
    )
    history.record_outcome(
        recommendation_id=bad_id,
        horizon_days=30,
        evaluated_at=generated + timedelta(days=30),
        entry_price=100.0,
        exit_price=90.0,
        source_provider="test",
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET horizon_days = 31 WHERE recommendation_id = ?",
            (bad_id,),
        )

    report = RecommendationCalibrationService(database=database).get_report(model_version="current")
    assert report.model_version == "current"
    assert all(proposal.sample_count == 0 for proposal in report.proposals)

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import RecommendationHistoryRepository
from app.services.recommendation_calibration_service import RecommendationCalibrationService


def _seed(database: AthenaDatabase, index: int, day_offset: int) -> int:
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index)
    recommendation_id = history.create_recommendation(
        symbol=f"T{index}", action="buy", score=75, conviction=0.9,
        horizon_days=30, generated_at=generated, data_cutoff_at=generated,
        model_version="v1", rationale={}, input_snapshot={},
    )
    history.record_outcome(
        recommendation_id=recommendation_id, horizon_days=30,
        evaluated_at=generated + timedelta(days=30 + day_offset),
        entry_price=100.0, exit_price=110.0 if index % 2 == 0 else 90.0,
        source_provider="test",
    )
    return recommendation_id


def test_invalid_evaluation_timestamp_cannot_be_silently_excluded_from_calibration(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(20):
        _seed(database, index, index // 10)

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET evaluated_at = ? WHERE id = 1",
            ("not-a-timestamp",),
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="evaluated_at inválido"):
        RecommendationCalibrationService(
            database=database, minimum_sample_size=20,
        ).get_report(model_version="v1", horizon_days=30)


def test_timezone_naive_evaluation_timestamp_cannot_support_longitudinal_evidence(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(20):
        _seed(database, index, index // 10)

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_recommendation_outcomes SET evaluated_at = ? WHERE id = 1",
            ("2026-02-01T12:00:00",),
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="sin zona horaria"):
        RecommendationCalibrationService(
            database=database, minimum_sample_size=20,
        ).get_report(model_version="v1", horizon_days=30)

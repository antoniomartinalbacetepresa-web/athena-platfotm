from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_evaluation_schedule_service import (
    RecommendationEvaluationScheduleService,
)


def _create_recommendation(
    database: AthenaDatabase,
    *,
    generated_at: datetime,
) -> int:
    return RecommendationHistoryRepository(database=database).create_recommendation(
        symbol="AAPL",
        action="buy",
        score=80,
        conviction=0.8,
        horizon_days=90,
        generated_at=generated_at,
        data_cutoff_at=generated_at,
        model_version="v1",
        rationale={},
        input_snapshot={},
    )


def test_schedule_marks_only_elapsed_horizons_due(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    generated = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _create_recommendation(database, generated_at=generated)

    report = RecommendationEvaluationScheduleService(
        database=database,
        horizons=(7, 30, 90),
    ).get_report(as_of=generated + timedelta(days=40))

    assert report.due_count == 2
    assert report.future_count == 1
    assert report.completed_count == 0
    assert [item.horizon_days for item in report.due] == [7, 30]


def test_schedule_excludes_completed_horizon(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    generated = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recommendation_id = _create_recommendation(database, generated_at=generated)
    history = RecommendationHistoryRepository(database=database)
    history.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=7,
        evaluated_at=generated + timedelta(days=7),
        entry_price=100,
        exit_price=105,
        source_provider="test",
    )

    report = RecommendationEvaluationScheduleService(
        database=database,
        horizons=(7, 30),
    ).get_report(as_of=generated + timedelta(days=40))

    assert report.completed_count == 1
    assert report.due_count == 1
    assert report.due[0].horizon_days == 30


def test_default_schedule_uses_learning_horizons(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    generated = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _create_recommendation(database, generated_at=generated)

    report = RecommendationEvaluationScheduleService(
        database=database
    ).get_report(as_of=generated + timedelta(days=400))

    assert report.horizons == (7, 30, 90, 180, 365)
    assert report.due_count == 5
    assert report.future_count == 0


def test_schedule_requires_timezone_aware_as_of(tmp_path: Path) -> None:
    service = RecommendationEvaluationScheduleService(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.get_report(as_of=datetime(2026, 1, 1))


def test_schedule_rejects_invalid_horizons(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="horizons"):
        RecommendationEvaluationScheduleService(
            database=AthenaDatabase(tmp_path / "athena.db"),
            horizons=(7, 0, 30),
        )

from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


def test_learning_status_is_safe_on_empty_history(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    status = RecommendationLearningStatusService(
        database=database
    ).get_status(
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert status["status"] == "learning_diagnostics_only"
    assert status["performance"]["sampleCount"] == 0
    assert status["calibration"]["autoApply"] is False
    assert status["evaluationSchedule"]["dueCount"] == 0
    assert status["drift"] is None
    assert status["automaticModelMutation"] is False


def test_learning_status_includes_drift_only_with_complete_filter(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    service = RecommendationLearningStatusService(database=database)
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    without_horizon = service.get_status(
        as_of=as_of,
        model_version="v1",
    )
    with_filter = service.get_status(
        as_of=as_of,
        model_version="v1",
        horizon_days=30,
    )

    assert without_horizon["drift"] is None
    assert with_filter["drift"] is not None
    assert with_filter["drift"]["status"] == "insufficient_sample"
    assert with_filter["filters"] == {
        "modelVersion": "v1",
        "horizonDays": 30,
    }

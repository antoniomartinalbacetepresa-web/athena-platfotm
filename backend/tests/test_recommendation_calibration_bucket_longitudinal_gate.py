from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_calibration_service import (
    RecommendationCalibrationService,
)


def _seed(
    database: AthenaDatabase,
    *,
    index: int,
    conviction: float,
    evaluation_day_offset: int,
) -> None:
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(
        minutes=index
    )
    recommendation_id = history.create_recommendation(
        symbol=f"B{index}",
        action="buy",
        score=75,
        conviction=conviction,
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
        evaluated_at=generated + timedelta(days=30 + evaluation_day_offset),
        entry_price=100.0,
        exit_price=110.0 if index % 2 == 0 else 90.0,
        source_provider="test",
    )


def test_global_time_span_cannot_substitute_for_bucket_longitudinal_evidence(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    # The overall outcome population spans two days, but each conviction bucket
    # exists on only one day. A global gate would incorrectly permit both buckets
    # to propose calibration changes from cross-sectional batches.
    for index in range(10):
        _seed(
            database,
            index=index,
            conviction=0.9,
            evaluation_day_offset=0,
        )
    for index in range(10, 20):
        _seed(
            database,
            index=index,
            conviction=0.6,
            evaluation_day_offset=1,
        )

    report = RecommendationCalibrationService(
        database=database,
        minimum_sample_size=10,
    ).get_report(model_version="v1", horizon_days=30)

    assert report.longitudinal_evidence_ready is True
    assert report.distinct_evaluation_days == 2
    assert report.evaluation_span_days == 1

    medium = next(item for item in report.proposals if item.label == "medium")
    very_high = next(item for item in report.proposals if item.label == "very_high")
    assert medium.sample_count == 10
    assert very_high.sample_count == 10
    assert medium.status == "insufficient_longitudinal_evidence"
    assert very_high.status == "insufficient_longitudinal_evidence"
    assert medium.proposed_delta is None
    assert very_high.proposed_delta is None

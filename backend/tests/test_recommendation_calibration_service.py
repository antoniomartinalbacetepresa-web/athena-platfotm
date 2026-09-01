from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_calibration_service import (
    RecommendationCalibrationService,
)


def _seed_directional(
    database: AthenaDatabase,
    *,
    conviction: float,
    success: bool,
    index: int,
) -> None:
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(
        minutes=index
    )
    recommendation_id = history.create_recommendation(
        symbol=f"S{index}",
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
        evaluated_at=generated + timedelta(days=30),
        entry_price=100.0,
        exit_price=110.0 if success else 90.0,
        source_provider="test",
    )


def test_calibration_requires_minimum_sample_before_proposing_change(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(5):
        _seed_directional(
            database,
            conviction=0.9,
            success=True,
            index=index,
        )

    report = RecommendationCalibrationService(
        database=database,
        minimum_sample_size=10,
    ).get_report(model_version="v1", horizon_days=30)

    very_high = next(
        proposal for proposal in report.proposals if proposal.label == "very_high"
    )
    assert very_high.sample_count == 5
    assert very_high.status == "insufficient_sample"
    assert very_high.calibration_gap is None
    assert very_high.proposed_delta is None
    assert report.to_api_dict()["autoApply"] is False


def test_calibration_proposal_is_bounded_and_review_only(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(20):
        _seed_directional(
            database,
            conviction=0.9,
            success=index < 10,
            index=index,
        )

    report = RecommendationCalibrationService(
        database=database,
        minimum_sample_size=20,
        learning_rate=0.5,
        maximum_step=0.05,
    ).get_report(model_version="v1", horizon_days=30)

    very_high = next(
        proposal for proposal in report.proposals if proposal.label == "very_high"
    )
    assert very_high.sample_count == 20
    assert very_high.observed_accuracy == pytest.approx(0.5)
    assert very_high.average_conviction == pytest.approx(0.9)
    assert very_high.calibration_gap == pytest.approx(-0.4)
    assert very_high.proposed_delta == pytest.approx(-0.05)
    assert very_high.status == "review_required"


def test_calibration_can_propose_small_positive_adjustment(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(10):
        _seed_directional(
            database,
            conviction=0.6,
            success=index < 8,
            index=index,
        )

    report = RecommendationCalibrationService(
        database=database,
        minimum_sample_size=10,
        learning_rate=0.25,
        maximum_step=0.1,
    ).get_report()

    medium = next(proposal for proposal in report.proposals if proposal.label == "medium")
    assert medium.observed_accuracy == pytest.approx(0.8)
    assert medium.average_conviction == pytest.approx(0.6)
    assert medium.calibration_gap == pytest.approx(0.2)
    assert medium.proposed_delta == pytest.approx(0.05)


def test_calibration_configuration_is_guarded(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    with pytest.raises(ValueError, match="minimum_sample_size"):
        RecommendationCalibrationService(database=database, minimum_sample_size=0)
    with pytest.raises(ValueError, match="learning_rate"):
        RecommendationCalibrationService(database=database, learning_rate=1.5)
    with pytest.raises(ValueError, match="maximum_step"):
        RecommendationCalibrationService(database=database, maximum_step=0.5)

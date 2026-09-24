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
    evaluation_day_offset: int = 0,
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
        evaluated_at=(
            generated + timedelta(days=30 + evaluation_day_offset)
        ),
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


def test_same_day_batch_cannot_propose_calibration_change(tmp_path: Path) -> None:
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
    assert very_high.status == "insufficient_longitudinal_evidence"
    assert very_high.calibration_gap is None
    assert very_high.proposed_delta is None
    assert report.distinct_evaluation_days == 1
    assert report.evaluation_span_days == 0
    assert report.longitudinal_evidence_ready is False


def test_calibration_proposal_is_bounded_and_review_only_with_longitudinal_evidence(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(20):
        _seed_directional(
            database,
            conviction=0.9,
            success=index < 10,
            index=index,
            evaluation_day_offset=index // 10,
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
    assert report.distinct_evaluation_days == 2
    assert report.evaluation_span_days == 1
    assert report.longitudinal_evidence_ready is True


def test_calibration_can_propose_small_positive_adjustment(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    for index in range(10):
        _seed_directional(
            database,
            conviction=0.6,
            success=index < 8,
            index=index,
            evaluation_day_offset=index // 5,
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
    with pytest.raises(ValueError, match="minimum_distinct_evaluation_days"):
        RecommendationCalibrationService(
            database=database,
            minimum_distinct_evaluation_days=1,
        )
    with pytest.raises(ValueError, match="minimum_evaluation_span_days"):
        RecommendationCalibrationService(
            database=database,
            minimum_evaluation_span_days=0,
        )



def test_calibration_rejects_outcome_evaluated_before_frozen_horizon(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = history.create_recommendation(
        symbol="EARLY",
        action="buy",
        score=80,
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
        evaluated_at=generated + timedelta(days=10),
        entry_price=100.0,
        exit_price=120.0,
        source_provider="test",
    )

    with pytest.raises(RuntimeError, match="integridad temporal/horizonte OOS"):
        RecommendationCalibrationService(
            database=database,
            minimum_sample_size=1,
        ).get_report(model_version="v1", horizon_days=30)

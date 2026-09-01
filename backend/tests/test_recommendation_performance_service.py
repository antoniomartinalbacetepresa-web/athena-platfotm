from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_performance_service import (
    RecommendationPerformanceService,
)


def _seed(
    database: AthenaDatabase,
    *,
    action: str,
    conviction: float,
    entry: float,
    exit: float,
    benchmark: float | None,
    horizon: int = 30,
    model_version: str = "v1",
) -> None:
    history = RecommendationHistoryRepository(database=database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = history.create_recommendation(
        symbol=f"{action}-{conviction}",
        action=action,
        score=70,
        conviction=conviction,
        horizon_days=horizon,
        generated_at=generated,
        data_cutoff_at=generated - timedelta(minutes=1),
        model_version=model_version,
        rationale={},
        input_snapshot={},
    )
    history.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=horizon,
        evaluated_at=generated + timedelta(days=horizon),
        entry_price=entry,
        exit_price=exit,
        benchmark_return=benchmark,
        source_provider="test",
    )


def test_performance_measures_direction_without_inventing_hold_accuracy(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _seed(database, action="buy", conviction=0.9, entry=100, exit=120, benchmark=0.05)
    _seed(database, action="buy", conviction=0.8, entry=100, exit=90, benchmark=0.02)
    _seed(database, action="sell", conviction=0.75, entry=100, exit=80, benchmark=-0.05)
    _seed(database, action="reduce", conviction=0.6, entry=100, exit=105, benchmark=0.03)
    _seed(database, action="hold", conviction=0.55, entry=100, exit=101, benchmark=0.01)

    report = RecommendationPerformanceService(database=database).get_report()
    api = report.to_api_dict()

    assert report.sample_count == 5
    assert report.directional_sample_count == 4
    assert report.directional_success_count == 2
    assert report.directional_accuracy == pytest.approx(0.5)
    assert report.by_action["buy"]["sampleCount"] == 2
    assert report.by_action["buy"]["directionalAccuracy"] == pytest.approx(0.5)
    assert report.by_action["sell"]["directionalAccuracy"] == pytest.approx(1.0)
    assert report.by_action["reduce"]["directionalAccuracy"] == pytest.approx(0.0)
    assert report.by_action["hold"]["directionalAccuracy"] is None
    assert report.by_action["hold"]["directionalSuccessCount"] is None
    assert api["holdAccuracyStatus"] == (
        "not_defined_without_validated_tolerance_band"
    )


def test_performance_filters_model_version_and_horizon(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _seed(
        database,
        action="buy",
        conviction=0.9,
        entry=100,
        exit=110,
        benchmark=0.02,
        horizon=30,
        model_version="v1",
    )
    _seed(
        database,
        action="buy",
        conviction=0.9,
        entry=100,
        exit=90,
        benchmark=0.01,
        horizon=90,
        model_version="v1",
    )
    _seed(
        database,
        action="sell",
        conviction=0.9,
        entry=100,
        exit=80,
        benchmark=-0.03,
        horizon=30,
        model_version="v2",
    )

    report = RecommendationPerformanceService(database=database).get_report(
        model_version="v1",
        horizon_days=30,
    )

    assert report.sample_count == 1
    assert report.model_version == "v1"
    assert report.horizon_days == 30
    assert report.directional_accuracy == pytest.approx(1.0)
    assert report.average_realized_return == pytest.approx(0.1)
    assert report.average_excess_return == pytest.approx(0.08)


def test_conviction_buckets_keep_sample_size_visible(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _seed(database, action="buy", conviction=0.92, entry=100, exit=110, benchmark=0)
    _seed(database, action="sell", conviction=0.88, entry=100, exit=90, benchmark=0)
    _seed(database, action="buy", conviction=0.4, entry=100, exit=90, benchmark=0)

    report = RecommendationPerformanceService(database=database).get_report()

    very_high = next(
        bucket for bucket in report.conviction_buckets if bucket["label"] == "very_high"
    )
    low = next(bucket for bucket in report.conviction_buckets if bucket["label"] == "low")

    assert very_high["sampleCount"] == 2
    assert very_high["directionalAccuracy"] == pytest.approx(1.0)
    assert very_high["averageConviction"] == pytest.approx(0.9)
    assert low["sampleCount"] == 1
    assert low["directionalAccuracy"] == pytest.approx(0.0)


def test_empty_performance_report_is_explicit(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    report = RecommendationPerformanceService(database=database).get_report()

    assert report.sample_count == 0
    assert report.average_realized_return is None
    assert report.directional_accuracy is None
    assert all(item["sampleCount"] == 0 for item in report.by_action.values())


def test_performance_rejects_invalid_filters(tmp_path: Path) -> None:
    service = RecommendationPerformanceService(
        database=AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="horizon_days"):
        service.get_report(horizon_days=0)

    with pytest.raises(ValueError, match="model_version"):
        service.get_report(model_version="   ")

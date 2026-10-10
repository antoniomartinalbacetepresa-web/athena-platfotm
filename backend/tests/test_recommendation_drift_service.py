from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_drift_service import RecommendationDriftService


def _benchmark_evidence(
    *, generated_at: datetime, due_at: datetime, benchmark_return: float
) -> dict[str, object]:
    return {
        "status": "resolved",
        "benchmarkSymbol": "SPY",
        "benchmarkInstrumentId": 999,
        "entryPrice": 100.0,
        "exitPrice": 100.0 * (1.0 + benchmark_return),
        "benchmarkReturn": benchmark_return,
        "entryObservedAt": generated_at.isoformat(),
        "exitObservedAt": due_at.isoformat(),
        "entryRetrievedAt": generated_at.isoformat(),
        "exitRetrievedAt": due_at.isoformat(),
        "entrySourceProvider": "test_benchmark",
        "exitSourceProvider": "test_benchmark",
    }


def _seed(
    database: AthenaDatabase,
    *,
    generated_at: datetime,
    success: bool,
    excess_return: float,
    index: int,
) -> None:
    history = RecommendationHistoryRepository(database=database)
    recommendation_id = history.create_recommendation(
        symbol=f"S{index}",
        benchmark_symbol="SPY",
        action="buy",
        score=75,
        conviction=0.8,
        horizon_days=30,
        generated_at=generated_at,
        data_cutoff_at=generated_at,
        model_version="v1",
        rationale={},
        input_snapshot={},
    )
    realized_return = 0.10 if success else -0.10
    benchmark_return = realized_return - excess_return
    due_at = generated_at + timedelta(days=30)
    history.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=30,
        evaluated_at=due_at,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + realized_return),
        benchmark_return=benchmark_return,
        benchmark_evidence=_benchmark_evidence(
            generated_at=generated_at,
            due_at=due_at,
            benchmark_return=benchmark_return,
        ),
        source_provider="test",
    )


def test_drift_requires_sample_in_both_windows(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for index in range(5):
        _seed(
            database,
            generated_at=as_of - timedelta(days=30 + index),
            success=True,
            excess_return=0.02,
            index=index,
        )

    report = RecommendationDriftService(
        database=database,
        minimum_sample_size=10,
    ).get_report(model_version="v1", horizon_days=30, as_of=as_of)

    assert report.status == "insufficient_sample"
    assert report.accuracy_delta is None
    assert report.to_api_dict()["autoAction"] is False


def test_drift_flags_joint_accuracy_and_excess_degradation(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    for index in range(20):
        _seed(
            database,
            generated_at=as_of - timedelta(days=200 + index),
            success=index < 16,
            excess_return=0.04,
            index=index,
        )
    for index in range(20, 40):
        _seed(
            database,
            generated_at=as_of - timedelta(days=20 + (index - 20)),
            success=index < 28,
            excess_return=-0.01,
            index=index,
        )

    report = RecommendationDriftService(
        database=database,
        recent_window_days=90,
        baseline_window_days=365,
        minimum_sample_size=20,
        accuracy_drop_threshold=0.10,
        excess_return_drop_threshold=0.02,
    ).get_report(model_version="v1", horizon_days=30, as_of=as_of)

    assert report.baseline.sample_count == 20
    assert report.recent.sample_count == 20
    assert report.baseline.directional_accuracy == pytest.approx(0.8)
    assert report.recent.directional_accuracy == pytest.approx(0.4)
    assert report.accuracy_delta == pytest.approx(-0.4)
    assert report.baseline.average_excess_return == pytest.approx(0.04)
    assert report.recent.average_excess_return == pytest.approx(-0.01)
    assert report.excess_return_delta == pytest.approx(-0.05)
    assert report.status == "degraded"


def test_drift_watch_when_only_one_metric_crosses_threshold(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    for index in range(10):
        _seed(
            database,
            generated_at=as_of - timedelta(days=180 + index),
            success=index < 8,
            excess_return=0.01,
            index=index,
        )
    for index in range(10, 20):
        _seed(
            database,
            generated_at=as_of - timedelta(days=20 + (index - 10)),
            success=index < 15,
            excess_return=0.005,
            index=index,
        )

    report = RecommendationDriftService(
        database=database,
        minimum_sample_size=10,
        accuracy_drop_threshold=0.20,
        excess_return_drop_threshold=0.02,
    ).get_report(model_version="v1", horizon_days=30, as_of=as_of)

    assert report.accuracy_delta == pytest.approx(-0.3)
    assert report.excess_return_delta == pytest.approx(-0.005)
    assert report.status == "watch"


def test_drift_stable_when_changes_stay_within_thresholds(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    for index in range(10):
        _seed(
            database,
            generated_at=as_of - timedelta(days=180 + index),
            success=index < 7,
            excess_return=0.02,
            index=index,
        )
    for index in range(10, 20):
        _seed(
            database,
            generated_at=as_of - timedelta(days=20 + (index - 10)),
            success=index < 17,
            excess_return=0.015,
            index=index,
        )

    report = RecommendationDriftService(
        database=database,
        minimum_sample_size=10,
        accuracy_drop_threshold=0.10,
        excess_return_drop_threshold=0.02,
    ).get_report(model_version="v1", horizon_days=30, as_of=as_of)

    assert report.status == "stable"


def test_drift_validates_configuration_and_time(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    with pytest.raises(ValueError, match="ventanas"):
        RecommendationDriftService(database=database, recent_window_days=0)

    service = RecommendationDriftService(database=database)
    with pytest.raises(ValueError, match="zona horaria"):
        service.get_report(
            model_version="v1",
            horizon_days=30,
            as_of=datetime(2026, 9, 1),
        )
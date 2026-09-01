from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)


def _repository(tmp_path: Path) -> RecommendationHistoryRepository:
    return RecommendationHistoryRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def _create(repository: RecommendationHistoryRepository) -> int:
    generated = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    return repository.create_recommendation(
        symbol="AAPL",
        action="buy",
        score=82.5,
        conviction=0.78,
        risk_score=35.0,
        horizon_days=90,
        generated_at=generated,
        data_cutoff_at=generated - timedelta(minutes=5),
        model_version="athena-recommendation-v1",
        rationale={"summary": "quality plus valuation"},
        input_snapshot={"price": 200.0, "pe": 28.0},
    )


def test_recommendation_preserves_point_in_time_snapshot(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    recommendation_id = _create(repository)

    recommendation = repository.get_recommendation(recommendation_id)

    assert recommendation is not None
    assert recommendation["symbol"] == "AAPL"
    assert recommendation["action"] == "buy"
    assert recommendation["score"] == pytest.approx(82.5)
    assert recommendation["conviction"] == pytest.approx(0.78)
    assert recommendation["model_version"] == "athena-recommendation-v1"
    assert recommendation["rationale"] == {"summary": "quality plus valuation"}
    assert recommendation["input_snapshot"] == {"pe": 28.0, "price": 200.0}


def test_recommendation_rejects_future_data_cutoff(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    generated = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="data_cutoff_at"):
        repository.create_recommendation(
            symbol="AAPL",
            action="buy",
            score=80,
            conviction=0.8,
            horizon_days=30,
            generated_at=generated,
            data_cutoff_at=generated + timedelta(seconds=1),
            model_version="v1",
            rationale={},
            input_snapshot={},
        )


def test_recommendation_rejects_naive_timestamps(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="zona horaria"):
        repository.create_recommendation(
            symbol="AAPL",
            action="hold",
            score=50,
            conviction=0.5,
            horizon_days=30,
            generated_at=datetime(2026, 9, 1, 12, 0),
            data_cutoff_at=datetime(2026, 9, 1, 11, 59, tzinfo=timezone.utc),
            model_version="v1",
            rationale={},
            input_snapshot={},
        )


def test_outcome_calculates_realized_and_excess_return(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    recommendation_id = _create(repository)

    repository.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=30,
        evaluated_at=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        entry_price=200.0,
        exit_price=220.0,
        benchmark_return=0.04,
        max_drawdown=-0.08,
        source_provider="yahoo",
    )

    outcomes = repository.list_outcomes(recommendation_id)
    assert len(outcomes) == 1
    assert outcomes[0]["realized_return"] == pytest.approx(0.10)
    assert outcomes[0]["benchmark_return"] == pytest.approx(0.04)
    assert outcomes[0]["excess_return"] == pytest.approx(0.06)
    assert outcomes[0]["max_drawdown"] == pytest.approx(-0.08)


def test_outcome_cannot_be_evaluated_before_horizon(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    recommendation_id = _create(repository)

    with pytest.raises(ValueError, match="horizonte"):
        repository.record_outcome(
            recommendation_id=recommendation_id,
            horizon_days=7,
            evaluated_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            entry_price=200.0,
            exit_price=201.0,
            source_provider="yahoo",
        )


def test_outcome_accepts_exact_horizon_boundary(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    recommendation_id = _create(repository)

    outcome_id = repository.record_outcome(
        recommendation_id=recommendation_id,
        horizon_days=7,
        evaluated_at=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        entry_price=200.0,
        exit_price=202.0,
        source_provider="yahoo",
    )

    assert outcome_id > 0


def test_recommendation_validates_action_scores_and_horizon(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="action"):
        repository.create_recommendation(
            symbol="AAPL",
            action="strong_buy",
            score=80,
            conviction=0.8,
            horizon_days=30,
            generated_at=now,
            data_cutoff_at=now,
            model_version="v1",
            rationale={},
            input_snapshot={},
        )

    with pytest.raises(ValueError, match="score"):
        repository.create_recommendation(
            symbol="AAPL",
            action="buy",
            score=101,
            conviction=0.8,
            horizon_days=30,
            generated_at=now,
            data_cutoff_at=now,
            model_version="v1",
            rationale={},
            input_snapshot={},
        )

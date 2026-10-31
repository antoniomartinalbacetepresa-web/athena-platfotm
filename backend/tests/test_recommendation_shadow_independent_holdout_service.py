from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)


class FakeDatasetService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "featureSchemaVersion": "shadow-evidence-v1",
            "rowCount": len(self.rows),
            "rows": self.rows,
        }


def _row(*, index: int, cutoff: datetime, evaluated: datetime, horizon: int = 30):
    signal = (index - 20) / 100.0
    return {
        "snapshotId": index + 1,
        "symbol": "TEST",
        "dataCutoffAt": cutoff.isoformat(),
        "outcomeEvaluatedAt": evaluated.isoformat(),
        "horizonDays": horizon,
        "features": {
            "technicalScore": float(index),
            "riskScore": float(index % 5),
        },
        "target": {
            "excessReturn": signal,
            "realizedReturn": signal,
            "benchmarkReturn": 0.0,
        },
    }


def _service(rows: list[dict], *, research_min: int = 30, holdout_min: int = 10):
    return RecommendationShadowIndependentHoldoutService(
        dataset_service=FakeDatasetService(rows),
        minimum_research_rows=research_min,
        minimum_holdout_rows=holdout_min,
    )


def test_freeze_creates_deterministic_immutable_research_artifact():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=60)
    rows = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    service = _service(rows)

    first = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)
    second = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)

    assert first["status"] == "shadow_model_frozen"
    assert first["fingerprint"] == second["fingerprint"]
    assert first["productionEligible"] is False
    assert first["advisoryStatus"] == "no_advice"
    assert first["policy"]["holdoutRefit"] is False
    assert "technicalScore" in first["features"]


def test_holdout_uses_only_features_strictly_after_frozen_cutoff():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=60)
    evaluation = start + timedelta(days=120)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    # These rows are visible to the dataset call but are not independent because
    # their feature timestamp belongs to the research era.
    leaked = [
        _row(index=40 + i, cutoff=cutoff, evaluated=cutoff + timedelta(days=1))
        for i in range(3)
    ]
    holdout = [
        _row(
            index=50 + i,
            cutoff=cutoff + timedelta(days=i + 1),
            evaluated=cutoff + timedelta(days=i + 2),
        )
        for i in range(12)
    ]
    rows = research + leaked + holdout
    service = _service(rows)
    frozen = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)

    result = service.evaluate(frozen_model=frozen, as_of=evaluation)

    assert result["status"] == "shadow_independent_holdout_evaluated"
    assert result["holdoutRowCount"] == 12
    assert result["excludedNotIndependentCount"] == len(research) + len(leaked)
    assert result["productionEligible"] is False
    assert result["policy"]["refit"] is False
    assert result["policy"]["selection"] is False
    assert result["policy"]["thresholdCalibration"] is False


def test_holdout_rejects_tampered_frozen_model():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=60)
    rows = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    service = _service(rows, holdout_min=1)
    frozen = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)
    frozen["intercept"] = float(frozen["intercept"]) + 1.0

    with pytest.raises(ValueError, match="modificado"):
        service.evaluate(frozen_model=frozen, as_of=cutoff + timedelta(days=10))


def test_holdout_does_not_use_outcomes_unknown_at_evaluation_cutoff():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=60)
    evaluation = start + timedelta(days=100)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    mature = [
        _row(
            index=50 + i,
            cutoff=cutoff + timedelta(days=i + 1),
            evaluated=cutoff + timedelta(days=i + 2),
        )
        for i in range(10)
    ]
    future = _row(
        index=99,
        cutoff=cutoff + timedelta(days=20),
        evaluated=evaluation + timedelta(days=1),
    )
    service = _service(research + mature + [future])
    frozen = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)

    result = service.evaluate(frozen_model=frozen, as_of=evaluation)

    assert result["status"] == "shadow_independent_holdout_evaluated"
    assert result["holdoutRowCount"] == 10
    assert result["excludedNotMatureCount"] == 1


def test_holdout_blocks_when_independent_sample_is_too_small():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=60)
    research = [
        _row(index=i, cutoff=start + timedelta(days=i), evaluated=start + timedelta(days=i + 1))
        for i in range(40)
    ]
    holdout = [
        _row(
            index=50 + i,
            cutoff=cutoff + timedelta(days=i + 1),
            evaluated=cutoff + timedelta(days=i + 2),
        )
        for i in range(4)
    ]
    service = _service(research + holdout)
    frozen = service.freeze(research_cutoff=cutoff, horizon_days=30, ridge_lambda=1.0)

    result = service.evaluate(
        frozen_model=frozen,
        as_of=cutoff + timedelta(days=30),
    )

    assert result["status"] == "insufficient_independent_holdout_data"
    assert result["row_count"] == 4
    assert result["minimum"] == 10
    assert result["productionEligible"] is False


def test_time_boundaries_must_be_timezone_aware():
    service = _service([], research_min=1, holdout_min=1)

    with pytest.raises(ValueError, match="zona horaria"):
        service.freeze(
            research_cutoff=datetime(2025, 1, 1),
            horizon_days=30,
            ridge_lambda=1.0,
        )

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_temporal_split_service import (
    RecommendationShadowTemporalSplitService,
)


UTC = timezone.utc
TRAIN_END = datetime(2026, 4, 1, tzinfo=UTC)
VALIDATION_END = datetime(2026, 7, 1, tzinfo=UTC)
AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


class FakeDatasetService:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def build(self, *, as_of, horizon_days=None, require_benchmark=False):
        self.calls.append(
            {
                "as_of": as_of,
                "horizon_days": horizon_days,
                "require_benchmark": require_benchmark,
            }
        )
        return {
            "featureSchemaVersion": "shadow-evidence-v1",
            "rowCount": len(self.rows),
            "rows": self.rows,
        }


def _row(snapshot_id: int, cutoff: str, evaluated: str) -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "instrumentId": 1,
        "symbol": "AAPL",
        "dataCutoffAt": cutoff,
        "horizonDays": 30,
        "outcomeDueAt": evaluated,
        "outcomeEvaluatedAt": evaluated,
        "target": {
            "realizedReturn": 0.10,
            "benchmarkReturn": 0.03,
            "excessReturn": 0.07,
        },
        "features": {"return20d": 0.05},
    }


def test_split_is_strictly_chronological_and_never_shuffles() -> None:
    rows = [
        _row(1, "2026-01-10T00:00:00+00:00", "2026-02-10T00:00:00+00:00"),
        _row(2, "2026-05-10T00:00:00+00:00", "2026-06-10T00:00:00+00:00"),
        _row(3, "2026-08-10T00:00:00+00:00", "2026-09-10T00:00:00+00:00"),
    ]
    dataset = FakeDatasetService(rows)

    result = RecommendationShadowTemporalSplitService(dataset_service=dataset).build(
        as_of=AS_OF,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
        horizon_days=30,
    )

    assert [row["snapshotId"] for row in result["train"]] == [1]
    assert [row["snapshotId"] for row in result["validation"]] == [2]
    assert [row["snapshotId"] for row in result["test"]] == [3]
    assert result["counts"] == {
        "source": 3,
        "train": 1,
        "validation": 1,
        "test": 1,
        "purged": 0,
    }
    assert dataset.calls[0]["require_benchmark"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["policy"]["productionEligibility"] is False


def test_split_purges_training_label_that_matures_after_train_boundary() -> None:
    rows = [
        _row(10, "2026-03-20T00:00:00+00:00", "2026-04-20T00:00:00+00:00"),
        _row(11, "2026-05-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"),
    ]

    result = RecommendationShadowTemporalSplitService(
        dataset_service=FakeDatasetService(rows)
    ).build(
        as_of=AS_OF,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
    )

    assert result["train"] == []
    assert [row["snapshotId"] for row in result["validation"]] == [11]
    assert result["counts"]["purged"] == 1
    assert result["purged"][0]["snapshotId"] == 10
    assert result["purged"][0]["reason"] == "train_label_not_known_at_boundary"


def test_split_purges_validation_label_that_matures_after_validation_boundary() -> None:
    rows = [
        _row(20, "2026-06-20T00:00:00+00:00", "2026-07-20T00:00:00+00:00"),
    ]

    result = RecommendationShadowTemporalSplitService(
        dataset_service=FakeDatasetService(rows)
    ).build(
        as_of=AS_OF,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
    )

    assert result["validation"] == []
    assert result["counts"]["purged"] == 1
    assert result["purged"][0]["reason"] == (
        "validation_label_not_known_at_boundary"
    )


def test_split_requires_ordered_timezone_aware_boundaries() -> None:
    service = RecommendationShadowTemporalSplitService(
        dataset_service=FakeDatasetService([])
    )

    with pytest.raises(ValueError, match="train_end < validation_end < as_of"):
        service.build(
            as_of=AS_OF,
            train_end=VALIDATION_END,
            validation_end=TRAIN_END,
        )

    with pytest.raises(ValueError, match="zona horaria"):
        service.build(
            as_of=AS_OF,
            train_end=datetime(2026, 4, 1),
            validation_end=VALIDATION_END,
        )


def test_split_rejects_missing_outcome_timing_metadata() -> None:
    broken = _row(
        30,
        "2026-01-10T00:00:00+00:00",
        "2026-02-10T00:00:00+00:00",
    )
    broken.pop("outcomeEvaluatedAt")

    service = RecommendationShadowTemporalSplitService(
        dataset_service=FakeDatasetService([broken])
    )

    with pytest.raises(ValueError, match="outcomeEvaluatedAt"):
        service.build(
            as_of=AS_OF,
            train_end=TRAIN_END,
            validation_end=VALIDATION_END,
        )

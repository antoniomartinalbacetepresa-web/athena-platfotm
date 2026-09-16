from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_walk_forward_plan_service import (
    RecommendationShadowWalkForwardPlanService,
)


class FakeDatasetService:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "featureSchemaVersion": "shadow-evidence-v1",
            "rowCount": len(self.rows),
            "rows": list(self.rows),
        }


class FakeSplitService:
    def __init__(self, deficient_test_end_day=None):
        self.deficient_test_end_day = deficient_test_end_day
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        validation_count = (
            1
            if kwargs["as_of"].day == self.deficient_test_end_day
            else 2
        )
        return {
            "counts": {
                "train": 4,
                "validation": validation_count,
                "test": 2,
                "purged": 1 if validation_count < 2 else 0,
            }
        }


def _rows(day_count=10, rows_per_day=2):
    rows = []
    for day in range(1, day_count + 1):
        timestamp = datetime(2025, 1, day, tzinfo=timezone.utc).isoformat()
        for item in range(rows_per_day):
            rows.append(
                {
                    "snapshotId": f"{day}-{item}",
                    "dataCutoffAt": timestamp,
                    "target": {"excessReturn": 9999.0 if item else -9999.0},
                }
            )
    return rows


def _service(rows=None, deficient_test_end_day=None):
    dataset = FakeDatasetService(_rows() if rows is None else rows)
    split = FakeSplitService(deficient_test_end_day=deficient_test_end_day)
    service = RecommendationShadowWalkForwardPlanService(
        dataset_service=dataset,
        split_service=split,
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
        step_rows=2,
        maximum_folds=3,
    )
    return service, dataset, split


def test_builds_expanding_folds_from_feature_timestamps_only():
    service, dataset, split = _service()

    result = service.build(
        as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
        horizon_days=30,
    )

    assert result["status"] == "shadow_walk_forward_plan_ready"
    assert result["proposalCount"] == 3
    assert result["readyFoldCount"] == 3
    assert [fold["train_end"].day for fold in result["folds"]] == [3, 4, 5]
    assert [fold["validation_end"].day for fold in result["folds"]] == [4, 5, 6]
    assert [fold["as_of"].day for fold in result["folds"]] == [5, 6, 7]
    assert all(
        fold["train_end"] < fold["validation_end"] < fold["as_of"]
        for fold in result["folds"]
    )
    assert result["policy"]["outcomeValuesUsedForBoundarySelection"] is False
    assert result["productionEligible"] is False
    assert dataset.calls[0]["require_benchmark"] is True
    assert len(split.calls) == 3


def test_rejects_proposed_fold_when_purging_leaves_too_few_rows():
    service, _, _ = _service(deficient_test_end_day=6)

    result = service.build(
        as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
        horizon_days=30,
    )

    assert result["proposalCount"] == 3
    assert result["readyFoldCount"] == 2
    rejected = [item for item in result["diagnostics"] if not item["accepted"]]
    assert len(rejected) == 1
    assert rejected[0]["boundaries"]["testEnd"].startswith("2025-01-06")
    assert rejected[0]["deficiencies"] == [
        {"partition": "validation", "rowCount": 1, "minimum": 2}
    ]


def test_does_not_call_split_service_when_feature_history_is_too_short():
    service, _, split = _service(rows=_rows(day_count=2))

    result = service.build(
        as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
        horizon_days=30,
    )

    assert result["status"] == "insufficient_shadow_walk_forward_plan_data"
    assert result["proposalCount"] == 0
    assert result["readyFoldCount"] == 0
    assert split.calls == []


def test_rejects_future_feature_timestamp():
    rows = _rows(day_count=3)
    rows.append(
        {
            "snapshotId": "future",
            "dataCutoffAt": datetime(2025, 2, 1, tzinfo=timezone.utc).isoformat(),
            "target": {"excessReturn": 0.0},
        }
    )
    service, _, _ = _service(rows=rows)

    with pytest.raises(ValueError, match="posterior a as_of"):
        service.build(
            as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
            horizon_days=30,
        )


def test_requires_timezone_aware_as_of():
    service, _, _ = _service()

    with pytest.raises(ValueError, match="zona horaria"):
        service.build(
            as_of=datetime(2025, 1, 10),
            horizon_days=30,
        )


def test_requires_positive_horizon():
    service, _, _ = _service()

    with pytest.raises(ValueError, match="positivo"):
        service.build(
            as_of=datetime(2025, 1, 10, tzinfo=timezone.utc),
            horizon_days=0,
        )

import math

import pytest

from app.services.recommendation_shadow_macro_candidate_comparison_service import (
    RecommendationShadowMacroCandidateComparisonService,
)


def _row(snapshot_id, technical_score, target):
    return {
        "snapshotId": snapshot_id,
        "features": {"technicalScore": float(technical_score)},
        "target": {"excessReturn": float(target)},
    }


def _split():
    train = [
        _row("train-1", -1.0, -0.03),
        _row("train-2", 0.0, -0.01),
        _row("train-3", 1.0, 0.02),
        _row("train-4", 2.0, 0.04),
    ]
    validation = [
        _row("validation-1", -0.5, -0.02),
        _row("validation-2", 1.5, 0.03),
    ]
    test = [
        _row("test-1", 0.5, 0.015),
        _row("test-2", 2.5, 0.05),
    ]
    return {
        "featureSchemaVersion": "shadow-evidence-v2",
        "horizonDays": 30,
        "train": train,
        "validation": validation,
        "test": test,
        "counts": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
    }


def _macro_preprocessing(split):
    values = {
        "train-1": -1.2,
        "train-2": -0.4,
        "train-3": 0.4,
        "train-4": 1.2,
        "validation-1": -0.8,
        "validation-2": 0.8,
        "test-1": 0.0,
        "test-2": 1.6,
    }
    return {
        "status": "shadow_macro_fold_preprocessing_fitted",
        "schemaVersion": "shadow-macro-fold-preprocessing-v1",
        "selectedFeatures": ["macro.cpi|US|pct"],
        "partitions": {
            partition: [
                {
                    "snapshotId": row["snapshotId"],
                    "values": {
                        "macro.cpi|US|pct": values[row["snapshotId"]]
                    },
                }
                for row in split[partition]
            ]
            for partition in ("train", "validation", "test")
        },
    }


def _base_evaluation(service, split):
    return service.evaluate_frozen_split(split=split)


def _service():
    return RecommendationShadowMacroCandidateComparisonService(
        minimum_train_rows=4,
        minimum_validation_rows=2,
        minimum_test_rows=2,
    )


def test_macro_comparison_is_paired_descriptive_and_never_promotes_candidate():
    service = _service()
    split = _split()
    result = service.compare(
        split=split,
        macro_preprocessing=_macro_preprocessing(split),
        base_evaluation=_base_evaluation(service, split),
    )

    assert result["status"] == "shadow_macro_candidate_comparison_evaluated"
    assert result["rowBinding"] == {
        "method": "exact_partition_order_and_snapshot_id",
        "partitionCounts": {"train": 4, "validation": 2, "test": 2},
        "sameFrozenSplit": True,
    }
    assert result["selectedMacroFeatures"] == ["macro.cpi|US|pct"]
    assert result["assessment"] == "not_assessed_without_precommitted_criteria"
    assert result["thresholdApplied"] is False
    assert result["candidateInfluence"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"]["thresholds"] == "none"
    assert result["policy"]["actions"] == "not_assigned"
    assert "macroHelps" not in result
    assert "recommended" not in result
    assert all(
        math.isfinite(value)
        for value in result["deltaAugmentedMinusBase"].values()
    )


def test_macro_comparison_fails_closed_when_snapshot_identity_does_not_match():
    service = _service()
    split = _split()
    macro = _macro_preprocessing(split)
    macro["partitions"]["test"][0]["snapshotId"] = "wrong-test-row"

    with pytest.raises(ValueError, match="snapshotId"):
        service.compare(
            split=split,
            macro_preprocessing=macro,
            base_evaluation=_base_evaluation(service, split),
        )


def test_macro_comparison_remains_blocked_when_macro_preprocessing_is_unavailable():
    service = _service()
    split = _split()
    result = service.compare(
        split=split,
        macro_preprocessing={
            "status": "insufficient_macro_fold_preprocessing_data",
            "reason": "no_train_macro_features",
        },
        base_evaluation=_base_evaluation(service, split),
    )

    assert result["status"] == "insufficient_macro_candidate_comparison_data"
    assert result["reason"] == "no_train_macro_features"
    assert result["thresholdApplied"] is False
    assert result["candidateInfluence"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False

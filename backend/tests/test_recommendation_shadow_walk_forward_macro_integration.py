from datetime import datetime, timezone

from app.services.recommendation_shadow_walk_forward_service import (
    RecommendationShadowWalkForwardService,
)


class FakeCandidateService:
    def __init__(self):
        self.calls = []

    def evaluate_frozen_split(self, *, split):
        self.calls.append(split)
        return {
            "status": "shadow_linear_candidate_evaluated",
            "test": {"mse": 0.8, "mae": 0.7, "signAccuracy": 0.6},
            "zeroExcessReturnBaseline": {
                "mse": 1.0,
                "mae": 0.8,
                "signAccuracy": 0.5,
            },
            "productionEligible": False,
        }


class FakeSplitService:
    def __init__(self):
        self.calls = []
        self.results = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls)
        split = {
            "schemaVersion": "shadow-calibration-v1",
            "train": [
                {
                    "snapshotId": f"train-{index}-1",
                    "macroResearchFeatures": [
                        {"key": "macro.cpi|US|pct", "value": 1.0}
                    ],
                },
                {
                    "snapshotId": f"train-{index}-2",
                    "macroResearchFeatures": [
                        {"key": "macro.cpi|US|pct", "value": 3.0}
                    ],
                },
            ],
            "validation": [
                {
                    "snapshotId": f"validation-{index}",
                    "macroResearchFeatures": [
                        {"key": "macro.cpi|US|pct", "value": 1000.0}
                    ],
                }
            ],
            "test": [
                {
                    "snapshotId": f"test-{index}",
                    "macroResearchFeatures": [
                        {"key": "macro.cpi|US|pct", "value": 1_000_000.0}
                    ],
                }
            ],
            "counts": {"train": 2, "validation": 1, "test": 1},
        }
        self.results.append(split)
        return split


def _dt(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _folds():
    return [
        {
            "train_end": _dt(2024, 1, 1),
            "validation_end": _dt(2024, 4, 1),
            "as_of": _dt(2024, 7, 1),
        },
        {
            "train_end": _dt(2024, 4, 1),
            "validation_end": _dt(2024, 7, 1),
            "as_of": _dt(2024, 10, 1),
        },
    ]


def test_walk_forward_fits_macro_preprocessing_inside_each_purged_fold_train_only():
    candidate = FakeCandidateService()
    split = FakeSplitService()
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        split_service=split,
        minimum_evaluated_folds=2,
    )

    result = service.evaluate(folds=_folds(), horizon_days=30)

    assert result["status"] == "shadow_walk_forward_evaluated"
    assert len(split.calls) == 2
    assert all(call["require_benchmark"] is True for call in split.calls)
    assert all(call["horizon_days"] == 30 for call in split.calls)
    for fold in result["folds"]:
        macro = fold["macroResearch"]
        assert macro["status"] == "shadow_macro_fold_preprocessing_fitted"
        assert macro["selectedFeatures"] == ["macro.cpi|US|pct"]
        assert macro["fitParameters"]["macro.cpi|US|pct"] == {
            "median": 2.0,
            "mean": 2.0,
            "populationStd": 1.0,
        }
        assert macro["partitionCounts"] == {"train": 2, "validation": 1, "test": 1}
        assert macro["candidateInfluence"] is False
        assert macro["productionEligible"] is False

    assert result["policy"]["macroResearchPreprocessing"] == "fit_inside_each_fold_train_only"
    assert result["policy"]["macroCandidateInfluence"] == (
        "disabled_until_oos_comparison_is_validated"
    )
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False


def test_walk_forward_macro_research_uses_the_exact_same_frozen_split_as_candidate():
    candidate = FakeCandidateService()
    split_service = FakeSplitService()
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        split_service=split_service,
        minimum_evaluated_folds=2,
    )

    service.evaluate(folds=_folds(), horizon_days=90)

    assert len(candidate.calls) == 2
    assert len(split_service.results) == 2
    for candidate_split, built_split in zip(candidate.calls, split_service.results):
        assert candidate_split is built_split

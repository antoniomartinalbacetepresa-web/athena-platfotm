from datetime import datetime, timezone

from app.services.recommendation_shadow_walk_forward_service import (
    RecommendationShadowWalkForwardService,
)


class FakeCandidateService:
    def __init__(self):
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
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

    def build(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls)
        return {
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
        }


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


def test_walk_forward_macro_research_does_not_change_candidate_inputs():
    candidate = FakeCandidateService()
    service = RecommendationShadowWalkForwardService(
        candidate_service=candidate,
        split_service=FakeSplitService(),
        minimum_evaluated_folds=2,
    )

    service.evaluate(folds=_folds(), horizon_days=90)

    assert len(candidate.calls) == 2
    for call, fold in zip(candidate.calls, _folds()):
        assert call == {
            "as_of": fold["as_of"],
            "train_end": fold["train_end"],
            "validation_end": fold["validation_end"],
            "horizon_days": 90,
        }

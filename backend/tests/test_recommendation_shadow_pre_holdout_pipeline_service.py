from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_pre_holdout_pipeline_service import (
    RecommendationShadowPreHoldoutPipelineService,
)


class FakeResearchPipeline:
    def __init__(self, *, eligible=True):
        self.eligible = eligible
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        raw_horizons = {
            "7": _raw_walk_forward(7),
            "30": _raw_walk_forward(30),
            "90": _raw_walk_forward(90),
        }
        return {
            "status": "shadow_research_pipeline_evaluated",
            "asOf": kwargs["as_of"].isoformat(),
            "walkForward": {
                "status": "shadow_auto_walk_forward_evaluated",
                "evaluation": {
                    "status": "shadow_multi_horizon_evaluated",
                    "horizons": raw_horizons,
                    "advisoryStatus": "no_advice",
                    "productionEligible": False,
                },
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            },
            "researchGate": {
                "status": (
                    "shadow_candidate_may_enter_action_calibration_research"
                    if self.eligible
                    else "shadow_candidate_fails_research_gate"
                ),
                "researchStageEligible": self.eligible,
                "horizons": {
                    "7": {
                        "horizonDays": 7,
                        "evaluated": True,
                        "passesResearchGate": self.eligible,
                    },
                    "30": {
                        "horizonDays": 30,
                        "evaluated": True,
                        "passesResearchGate": self.eligible,
                    },
                    "90": {
                        "horizonDays": 90,
                        "evaluated": True,
                        "passesResearchGate": False,
                    },
                },
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


class FakeSelector:
    def __init__(self, *, blocked_horizon=None):
        self.blocked_horizon = blocked_horizon
        self.calls = []

    def select(self, **kwargs):
        self.calls.append(kwargs)
        horizon = kwargs["horizon_days"]
        if horizon == self.blocked_horizon:
            return {
                "status": "insufficient_protocol_selection_evidence",
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            }
        return {
            "status": "shadow_ridge_protocol_selected",
            "horizonDays": horizon,
            "selectedRidgeLambda": 1.0,
            "selectionFingerprint": f"selection-{horizon}",
            "sourceWalkForwardFingerprint": f"walk-forward-{horizon}",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


class FakeGatedFreeze:
    def __init__(self):
        self.calls = []

    def freeze(self, **kwargs):
        self.calls.append(kwargs)
        horizon = kwargs["horizon_days"]
        return {
            "status": "shadow_research_gated_model_frozen",
            "horizonDays": horizon,
            "ridgeLambda": kwargs["protocol_selection"]["selectedRidgeLambda"],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


def _raw_walk_forward(horizon):
    return {
        "status": "shadow_walk_forward_evaluated",
        "horizonDays": horizon,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_research_gate_failure_prevents_all_selection_and_freezing():
    research = FakeResearchPipeline(eligible=False)
    selector = FakeSelector()
    freezer = FakeGatedFreeze()
    service = RecommendationShadowPreHoldoutPipelineService(
        research_pipeline_service=research,
        protocol_selection_service=selector,
        gated_freeze_service=freezer,
    )

    result = service.prepare(
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=(7, 30, 90),
    )

    assert result["status"] == "shadow_pre_holdout_blocked_by_research_gate"
    assert result["preparedHorizonCount"] == 0
    assert selector.calls == []
    assert freezer.calls == []
    assert result["productionEligible"] is False


def test_only_passing_horizons_are_selected_and_frozen():
    selector = FakeSelector()
    freezer = FakeGatedFreeze()
    service = RecommendationShadowPreHoldoutPipelineService(
        research_pipeline_service=FakeResearchPipeline(eligible=True),
        protocol_selection_service=selector,
        gated_freeze_service=freezer,
    )
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = service.prepare(as_of=cutoff, horizons=(7, 30, 90))

    assert result["status"] == "shadow_pre_holdout_candidates_frozen"
    assert result["preparedHorizonCount"] == 2
    assert set(result["frozenCandidates"]) == {"7", "30"}
    assert [call["horizon_days"] for call in selector.calls] == [7, 30]
    assert [call["horizon_days"] for call in freezer.calls] == [7, 30]
    assert all(call["research_cutoff"] == cutoff for call in freezer.calls)
    assert result["policy"]["manualLambdaSelection"] is False
    assert result["policy"]["holdoutEvidenceUsed"] is False
    assert result["productionEligible"] is False


def test_protocol_selection_failure_blocks_only_that_horizon():
    selector = FakeSelector(blocked_horizon=30)
    freezer = FakeGatedFreeze()
    service = RecommendationShadowPreHoldoutPipelineService(
        research_pipeline_service=FakeResearchPipeline(eligible=True),
        protocol_selection_service=selector,
        gated_freeze_service=freezer,
    )

    result = service.prepare(
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        horizons=(7, 30, 90),
    )

    assert result["preparedHorizonCount"] == 1
    assert set(result["frozenCandidates"]) == {"7"}
    assert result["blockedHorizons"] == [
        {
            "horizonDays": 30,
            "reason": "insufficient_protocol_selection_evidence",
        }
    ]
    assert [call["horizon_days"] for call in freezer.calls] == [7]


def test_pipeline_rejects_any_intermediate_production_promotion():
    research = FakeResearchPipeline(eligible=True)
    original = research.evaluate

    def unsafe_evaluate(**kwargs):
        result = original(**kwargs)
        result["walkForward"]["productionEligible"] = True
        return result

    research.evaluate = unsafe_evaluate
    service = RecommendationShadowPreHoldoutPipelineService(
        research_pipeline_service=research,
        protocol_selection_service=FakeSelector(),
        gated_freeze_service=FakeGatedFreeze(),
    )

    with pytest.raises(ValueError, match="productionEligible"):
        service.prepare(
            as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
            horizons=(7, 30, 90),
        )

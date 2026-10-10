from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_research_pipeline_service import (
    RecommendationShadowResearchPipelineService,
)


class FakeAutoWalkForwardService:
    def __init__(self, *, production_eligible=False, advisory_status="no_advice"):
        self.production_eligible = production_eligible
        self.advisory_status = advisory_status
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_auto_walk_forward_evaluated",
            "asOf": kwargs["as_of"].isoformat(),
            "requestedHorizons": list(kwargs["horizons"]),
            "evaluation": {
                "status": "shadow_multi_horizon_evaluated",
                "horizons": {},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            },
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
        }


class FakeGateService:
    def __init__(self, *, eligible=True, production_eligible=False):
        self.eligible = eligible
        self.production_eligible = production_eligible
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_candidate_may_enter_action_calibration_research",
            "researchStageEligible": self.eligible,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
        }


def test_connects_walk_forward_evidence_to_research_gate_without_advice():
    auto = FakeAutoWalkForwardService()
    gate = FakeGateService(eligible=True)
    service = RecommendationShadowResearchPipelineService(
        auto_walk_forward_service=auto,
        research_gate_service=gate,
    )
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)

    result = service.evaluate(as_of=cutoff, horizons=(7, 30, 90))

    assert auto.calls == [{"as_of": cutoff, "horizons": (7, 30, 90)}]
    assert gate.calls[0]["multi_horizon_evidence"]["status"] == (
        "shadow_multi_horizon_evaluated"
    )
    assert result["researchStageEligible"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["policy"]["freshUntouchedHoldoutBeforeProduction"] is True
    assert result["policy"]["automaticProductionPromotion"] is False


def test_research_gate_failure_remains_non_advisory_and_non_productive():
    service = RecommendationShadowResearchPipelineService(
        auto_walk_forward_service=FakeAutoWalkForwardService(),
        research_gate_service=FakeGateService(eligible=False),
    )

    result = service.evaluate(
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
        horizons=(30,),
    )

    assert result["researchStageEligible"] is False
    assert result["productionEligible"] is False


def test_fails_closed_if_any_upstream_stage_claims_production_eligibility():
    service = RecommendationShadowResearchPipelineService(
        auto_walk_forward_service=FakeAutoWalkForwardService(production_eligible=True),
        research_gate_service=FakeGateService(),
    )

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(
            as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
            horizons=(30,),
        )

    service = RecommendationShadowResearchPipelineService(
        auto_walk_forward_service=FakeAutoWalkForwardService(),
        research_gate_service=FakeGateService(production_eligible=True),
    )
    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(
            as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
            horizons=(30,),
        )


def test_fails_closed_if_upstream_stage_claims_advice():
    service = RecommendationShadowResearchPipelineService(
        auto_walk_forward_service=FakeAutoWalkForwardService(
            advisory_status="buy"
        ),
        research_gate_service=FakeGateService(),
    )

    with pytest.raises(ValueError, match="no_advice"):
        service.evaluate(
            as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
            horizons=(30,),
        )

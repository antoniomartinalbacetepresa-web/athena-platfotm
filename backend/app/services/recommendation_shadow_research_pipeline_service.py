from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.recommendation_shadow_auto_walk_forward_service import (
    RecommendationShadowAutoWalkForwardService,
)
from app.services.recommendation_shadow_research_gate_service import (
    RecommendationShadowResearchGateService,
)


class RecommendationShadowResearchPipelineService:
    """Run automatic PIT validation and the research-only advancement gate."""

    def __init__(
        self,
        *,
        auto_walk_forward_service: RecommendationShadowAutoWalkForwardService | None = None,
        research_gate_service: RecommendationShadowResearchGateService | None = None,
    ) -> None:
        self._auto_walk_forward_service = (
            auto_walk_forward_service
            if auto_walk_forward_service is not None
            else RecommendationShadowAutoWalkForwardService()
        )
        self._research_gate_service = (
            research_gate_service
            if research_gate_service is not None
            else RecommendationShadowResearchGateService()
        )

    def evaluate(
        self,
        *,
        as_of: datetime,
        horizons: tuple[int, ...] = RecommendationShadowAutoWalkForwardService.DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        auto_evidence = self._auto_walk_forward_service.evaluate(
            as_of=as_of,
            horizons=horizons,
        )
        self._assert_shadow_contract(auto_evidence, "auto_walk_forward")

        multi_horizon_evidence = auto_evidence.get("evaluation")
        if not isinstance(multi_horizon_evidence, dict):
            raise ValueError("La evaluación automática no contiene evidencia multi-horizonte válida.")
        self._assert_shadow_contract(multi_horizon_evidence, "multi_horizon")

        gate = self._research_gate_service.evaluate(
            multi_horizon_evidence=multi_horizon_evidence
        )
        self._assert_shadow_contract(gate, "research_gate")

        return {
            "status": "shadow_research_pipeline_evaluated",
            "asOf": auto_evidence.get("asOf"),
            "requestedHorizons": auto_evidence.get("requestedHorizons", []),
            "walkForward": auto_evidence,
            "researchGate": gate,
            "researchStageEligible": bool(gate.get("researchStageEligible")),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "sequence": "pit_plan_then_walk_forward_then_multi_horizon_then_research_gate",
                "gatePassMeaning": "research_only_not_investment_advice",
                "freshUntouchedHoldoutBeforeProduction": True,
                "actions": "not_assigned",
                "automaticModelMutation": False,
                "automaticProductionPromotion": False,
                "productionEligibility": False,
            },
        }

    def _assert_shadow_contract(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        advisory_status = payload.get("advisoryStatus")
        if advisory_status is not None and advisory_status != "no_advice":
            raise ValueError(f"{stage} violó el contrato no_advice.")

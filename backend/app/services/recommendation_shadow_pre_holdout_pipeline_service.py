from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_protocol_selection_service import (
    RecommendationShadowProtocolSelectionService,
)
from app.services.recommendation_shadow_research_pipeline_service import (
    RecommendationShadowResearchPipelineService,
)


class RecommendationShadowPreHoldoutPipelineService:
    """Prepare research-gated frozen candidates for future independent holdout.

    This orchestration removes manual assembly between research evaluation and
    model freezing. A horizon is frozen only when the global research gate and
    that exact horizon pass, protocol selection succeeds from the same
    walk-forward evidence, and the gated-freeze service validates all
    fingerprints. No output from this pipeline is investment advice.
    """

    def __init__(
        self,
        *,
        research_pipeline_service: RecommendationShadowResearchPipelineService | None = None,
        protocol_selection_service: RecommendationShadowProtocolSelectionService | None = None,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
    ) -> None:
        self._research_pipeline_service = (
            research_pipeline_service or RecommendationShadowResearchPipelineService()
        )
        self._protocol_selection_service = (
            protocol_selection_service or RecommendationShadowProtocolSelectionService()
        )
        self._gated_freeze_service = gated_freeze_service or RecommendationShadowGatedFreezeService(
            protocol_selection_service=self._protocol_selection_service
        )

    def prepare(
        self,
        *,
        as_of: datetime,
        horizons: tuple[int, ...] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]:
        research = self._research_pipeline_service.evaluate(
            as_of=as_of,
            horizons=horizons,
        )
        self._assert_shadow(research, "research_pipeline")

        gate = research.get("researchGate")
        if not isinstance(gate, dict):
            raise ValueError("El research pipeline no contiene researchGate válida.")
        self._assert_shadow(gate, "research_gate")

        walk_forward = research.get("walkForward")
        if not isinstance(walk_forward, dict):
            raise ValueError("El research pipeline no contiene walkForward válido.")
        self._assert_shadow(walk_forward, "walk_forward")
        multi_horizon = walk_forward.get("evaluation")
        if not isinstance(multi_horizon, dict):
            raise ValueError("walkForward no contiene evaluation multi-horizonte válida.")
        self._assert_shadow(multi_horizon, "multi_horizon")
        raw_horizons = multi_horizon.get("horizons")
        gate_horizons = gate.get("horizons")
        if not isinstance(raw_horizons, dict) or not isinstance(gate_horizons, dict):
            raise ValueError("Faltan horizontes para preparar el pre-holdout.")

        if gate.get("researchStageEligible") is not True:
            return {
                "status": "shadow_pre_holdout_blocked_by_research_gate",
                "asOf": research.get("asOf"),
                "researchGate": gate,
                "preparedHorizonCount": 0,
                "blockedHorizons": [],
                "frozenCandidates": {},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": self._policy(),
            }

        frozen_candidates: dict[str, dict[str, Any]] = {}
        blocked_horizons: list[dict[str, Any]] = []
        for key, gate_horizon in gate_horizons.items():
            if not isinstance(gate_horizon, dict):
                raise ValueError(f"Research gate inválida para horizonte {key}.")
            if gate_horizon.get("evaluated") is not True or gate_horizon.get(
                "passesResearchGate"
            ) is not True:
                continue

            horizon_days = self._positive_int(
                gate_horizon.get("horizonDays"), f"horizons[{key}].horizonDays"
            )
            raw = raw_horizons.get(str(horizon_days))
            if not isinstance(raw, dict):
                raw = raw_horizons.get(horizon_days)
            if not isinstance(raw, dict):
                raise ValueError(
                    f"No existe walk-forward fuente para horizonte {horizon_days}."
                )

            selection = self._protocol_selection_service.select(
                walk_forward_evidence=raw,
                horizon_days=horizon_days,
            )
            self._assert_shadow(selection, f"protocol_selection_{horizon_days}")
            if selection.get("status") != "shadow_ridge_protocol_selected":
                blocked_horizons.append(
                    {
                        "horizonDays": horizon_days,
                        "reason": selection.get(
                            "status", "protocol_selection_not_available"
                        ),
                    }
                )
                continue

            frozen = self._gated_freeze_service.freeze(
                research_gate=gate,
                protocol_selection=selection,
                research_cutoff=as_of,
                horizon_days=horizon_days,
            )
            self._assert_shadow(frozen, f"gated_freeze_{horizon_days}")
            if frozen.get("status") != "shadow_research_gated_model_frozen":
                blocked_horizons.append(
                    {
                        "horizonDays": horizon_days,
                        "reason": frozen.get("status", "gated_freeze_failed"),
                    }
                )
                continue
            frozen_candidates[str(horizon_days)] = frozen

        return {
            "status": (
                "shadow_pre_holdout_candidates_frozen"
                if frozen_candidates
                else "shadow_pre_holdout_no_candidate_frozen"
            ),
            "asOf": research.get("asOf"),
            "researchGate": gate,
            "preparedHorizonCount": len(frozen_candidates),
            "blockedHorizons": blocked_horizons,
            "frozenCandidates": frozen_candidates,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        status = payload.get("advisoryStatus")
        if status is not None and status != "no_advice":
            raise ValueError(f"{stage} violó el contrato no_advice.")

    def _positive_int(self, value: object, field: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero.") from exc
        if parsed <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return parsed

    def _policy(self) -> dict[str, Any]:
        return {
            "sequence": (
                "research_pipeline_then_validation_only_protocol_selection_"
                "then_same_evidence_gated_freeze"
            ),
            "globalResearchGateRequired": True,
            "perHorizonResearchGateRequired": True,
            "manualLambdaSelection": False,
            "sameWalkForwardEvidenceRequired": True,
            "holdoutEvidenceUsed": False,
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
            "productionEligibility": False,
        }

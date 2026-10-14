from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)
from app.services.recommendation_shadow_post_selection_multi_horizon_service import (
    RecommendationShadowPostSelectionMultiHorizonService,
)


class RecommendationShadowLiveCandidatePipelineService:
    """Trusted orchestration boundary for shadow live inference.

    Callers do not supply a prebuilt confirmation artifact. The pipeline derives
    it from the gated bundles and the persisted post-selection boundaries on each
    run, then passes that exact evidence to the live candidate builder. This
    avoids treating a deterministic SHA-256 fingerprint as proof of provenance.
    """

    def __init__(
        self,
        *,
        confirmation_service: RecommendationShadowPostSelectionMultiHorizonService | None = None,
        candidate_service: RecommendationShadowLiveCandidateService | None = None,
    ) -> None:
        self._confirmation_service = (
            confirmation_service or RecommendationShadowPostSelectionMultiHorizonService()
        )
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService(
            confirmation_service=self._confirmation_service
        )

    def build(
        self,
        *,
        symbol: str,
        as_of: datetime,
        gated_bundles: list[dict[str, Any]],
        horizons: tuple[int, ...] | list[int] = (
            7,
            30,
            90,
            180,
            365,
        ),
    ) -> dict[str, Any]:
        confirmation = self._confirmation_service.evaluate(
            gated_bundles=gated_bundles,
            as_of=as_of,
            horizons=horizons,
        )
        self._assert_shadow(confirmation, "multi_horizon_confirmation")

        candidate = self._candidate_service.build(
            symbol=symbol,
            as_of=as_of,
            gated_bundles=gated_bundles,
            confirmation_artifact=confirmation,
        )
        self._assert_shadow(candidate, "live_candidate")
        if candidate.get("recommendationCandidateReady") is not False:
            raise ValueError("El pipeline shadow intentó habilitar recommendationCandidateReady.")
        if candidate.get("action") is not None:
            raise ValueError("El pipeline shadow intentó asignar una acción.")
        if candidate.get("score") is not None or candidate.get("conviction") is not None:
            raise ValueError("El pipeline shadow intentó publicar score o convicción no calibrados.")

        return {
            **candidate,
            "confirmationDerivedInPipeline": True,
            "confirmationEvidenceFingerprint": confirmation.get(
                "confirmationEvidenceFingerprint"
            ),
            "policy": {
                **dict(candidate.get("policy") or {}),
                "confirmationSource": "recomputed_from_gated_bundles_and_persisted_selection_boundaries",
                "callerSuppliedConfirmationTrusted": False,
            },
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")

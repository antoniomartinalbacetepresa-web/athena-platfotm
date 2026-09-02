from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.recommendation_shadow_capture_service import (
    RecommendationShadowCaptureService,
)
from app.services.recommendation_shadow_live_candidate_pipeline_service import (
    RecommendationShadowLiveCandidatePipelineService,
)
from app.services.recommendation_shadow_live_candidate_store_service import (
    RecommendationShadowLiveCandidateStoreService,
)


class RecommendationShadowLiveCycleService:
    """Connect PIT evidence capture -> confirmed inference -> shadow persistence.

    This is the first end-to-end live candidate cycle, deliberately remaining
    outside the production recommendation table. The captured PIT snapshot is
    the immutable anchor used later for 7/30/90/180/365-day outcome evaluation.
    """

    def __init__(
        self,
        *,
        capture_service: RecommendationShadowCaptureService | None = None,
        candidate_pipeline: RecommendationShadowLiveCandidatePipelineService | None = None,
        store_service: RecommendationShadowLiveCandidateStoreService | None = None,
    ) -> None:
        self._capture_service = capture_service or RecommendationShadowCaptureService()
        self._candidate_pipeline = (
            candidate_pipeline or RecommendationShadowLiveCandidatePipelineService()
        )
        self._store_service = store_service or RecommendationShadowLiveCandidateStoreService()

    def run(
        self,
        *,
        symbol: str,
        as_of: datetime,
        gated_bundles: list[dict[str, Any]],
        benchmark_symbol: str,
        captured_at: datetime | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]:
        normalized_benchmark = str(benchmark_symbol or "").strip().upper()
        if not normalized_benchmark:
            raise ValueError("benchmark_symbol es obligatorio para el ciclo live shadow.")

        capture = self._capture_service.capture(
            symbol=symbol,
            as_of=as_of,
            captured_at=captured_at,
            benchmark_symbol=normalized_benchmark,
        )
        self._assert_no_advice(capture, "capture")
        if capture.get("status") != "captured_for_calibration":
            return {
                "status": "shadow_live_cycle_blocked",
                "stage": "pit_capture",
                "reason": capture.get("reason"),
                "blockers": list(capture.get("blockers") or []),
                "snapshotId": capture.get("snapshotId"),
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "recommendationCandidateReady": False,
            }
        snapshot_id = capture.get("snapshotId")
        if not isinstance(snapshot_id, int) or snapshot_id <= 0:
            raise RuntimeError("La captura PIT no devolvió snapshotId válido.")

        candidate = self._candidate_pipeline.build(
            symbol=symbol,
            as_of=as_of,
            gated_bundles=gated_bundles,
            horizons=horizons,
        )
        self._assert_shadow_candidate(candidate, "live_candidate")
        if candidate.get("status") != "shadow_live_candidate_inferred":
            return {
                "status": "shadow_live_cycle_blocked",
                "stage": "confirmed_inference",
                "reason": candidate.get("reason", candidate.get("status")),
                "snapshotId": snapshot_id,
                "candidate": candidate,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "recommendationCandidateReady": False,
            }

        persisted = self._store_service.store(
            snapshot_id=snapshot_id,
            candidate=candidate,
        )
        self._assert_shadow_candidate(persisted, "candidate_persistence")
        if persisted.get("status") != "shadow_live_candidate_persisted":
            raise RuntimeError("El store shadow no confirmó la persistencia del candidato.")

        return {
            "status": "shadow_live_cycle_persisted",
            "snapshotId": snapshot_id,
            "candidateId": persisted.get("candidateId"),
            "candidateFingerprint": persisted.get("candidateFingerprint"),
            "confirmationEvidenceFingerprint": persisted.get(
                "confirmationEvidenceFingerprint"
            ),
            "symbol": candidate.get("symbol"),
            "asOf": candidate.get("asOf"),
            "benchmarkSymbol": normalized_benchmark,
            "inferredHorizonCount": candidate.get("inferredHorizonCount"),
            "candidate": candidate,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "flow": "pit_capture_then_confirmed_frozen_model_inference_then_shadow_persistence",
                "outcomes": "measured_later_from_same_pit_snapshot",
                "action": "not_assigned",
                "score": "not_calibrated",
                "conviction": "not_calibrated",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }

    def _assert_no_advice(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")
        if payload.get("productionEligible") is True:
            raise ValueError(f"{stage} intentó habilitar producción.")

    def _assert_shadow_candidate(self, payload: dict[str, Any], stage: str) -> None:
        self._assert_no_advice(payload, stage)
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} debe declarar productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError(f"{stage} debe declarar recommendationCandidateReady=False.")
        if payload.get("action") is not None:
            raise ValueError(f"{stage} no puede asignar action.")
        if payload.get("score") is not None:
            raise ValueError(f"{stage} no puede publicar score no calibrado.")
        if payload.get("conviction") is not None:
            raise ValueError(f"{stage} no puede publicar conviction no calibrada.")

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
from app.services.recommendation_shadow_live_uncertainty_service import (
    RecommendationShadowLiveUncertaintyService,
)
from app.services.recommendation_shadow_live_uncertainty_store_service import (
    RecommendationShadowLiveUncertaintyStoreService,
)


class RecommendationShadowLiveCycleService:
    """Connect PIT evidence -> confirmed inference -> persistence -> uncertainty.

    The PIT snapshot anchors later outcome evaluation. Empirical uncertainty is
    reconstructed at the candidate's own ``asOf`` from earlier residuals of the
    exact same frozen model and is then immediately sealed. Re-running ATHENA
    later cannot silently replace the scenarios that existed at inference time.
    """

    def __init__(
        self,
        *,
        capture_service: RecommendationShadowCaptureService | None = None,
        candidate_pipeline: RecommendationShadowLiveCandidatePipelineService | None = None,
        store_service: RecommendationShadowLiveCandidateStoreService | None = None,
        uncertainty_service: RecommendationShadowLiveUncertaintyService | None = None,
        uncertainty_store_service: RecommendationShadowLiveUncertaintyStoreService | None = None,
    ) -> None:
        self._capture_service = capture_service or RecommendationShadowCaptureService()
        self._candidate_pipeline = (
            candidate_pipeline or RecommendationShadowLiveCandidatePipelineService()
        )
        self._store_service = store_service or RecommendationShadowLiveCandidateStoreService()
        self._uncertainty_service = (
            uncertainty_service or RecommendationShadowLiveUncertaintyService()
        )
        self._uncertainty_store_service = (
            uncertainty_store_service or RecommendationShadowLiveUncertaintyStoreService()
        )

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
        candidate_id = persisted.get("candidateId")
        if not isinstance(candidate_id, int) or candidate_id <= 0:
            raise RuntimeError("El store shadow no devolvió candidateId válido.")

        uncertainty = self._uncertainty_service.evaluate(candidate_id=candidate_id)
        self._assert_uncertainty_shadow(uncertainty)
        if uncertainty.get("candidateFingerprint") != persisted.get("candidateFingerprint"):
            raise RuntimeError("La incertidumbre shadow cambió el candidato persistido.")
        sealed_uncertainty = self._uncertainty_store_service.store(
            candidate_id=candidate_id,
            uncertainty=uncertainty,
        )
        self._assert_uncertainty_shadow(sealed_uncertainty)
        if sealed_uncertainty.get("candidateFingerprint") != persisted.get(
            "candidateFingerprint"
        ):
            raise RuntimeError("El sello de incertidumbre cambió el candidato persistido.")
        uncertainty_id = sealed_uncertainty.get("uncertaintyId")
        if not isinstance(uncertainty_id, int) or uncertainty_id <= 0:
            raise RuntimeError("El store de incertidumbre no devolvió uncertaintyId válido.")

        return {
            "status": "shadow_live_cycle_persisted",
            "snapshotId": snapshot_id,
            "candidateId": candidate_id,
            "candidateFingerprint": persisted.get("candidateFingerprint"),
            "confirmationEvidenceFingerprint": persisted.get(
                "confirmationEvidenceFingerprint"
            ),
            "uncertaintyId": uncertainty_id,
            "uncertaintyFingerprint": sealed_uncertainty.get("uncertaintyFingerprint"),
            "symbol": candidate.get("symbol"),
            "asOf": candidate.get("asOf"),
            "benchmarkSymbol": normalized_benchmark,
            "inferredHorizonCount": candidate.get("inferredHorizonCount"),
            "candidate": candidate,
            "uncertainty": uncertainty,
            "empiricalUncertaintyHorizonCount": uncertainty.get(
                "calibratedHorizonCount", 0
            ),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "flow": "pit_capture_then_confirmed_frozen_model_inference_then_candidate_persistence_then_ex_ante_uncertainty_then_immutable_uncertainty_seal",
                "outcomes": "measured_later_from_same_pit_snapshot",
                "uncertainty": "prior_non_overlapping_forward_residuals_same_frozen_model_only",
                "uncertaintyPersistence": "first_candidate_artifact_is_immutable_sha256_sealed",
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

    def _assert_uncertainty_shadow(self, payload: dict[str, Any]) -> None:
        self._assert_no_advice(payload, "uncertainty")
        if payload.get("productionEligible") is not False:
            raise ValueError("uncertainty debe declarar productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("uncertainty no puede habilitar recomendaciones.")
        if payload.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("uncertainty no puede promover calibración de acciones.")
        if payload.get("action") is not None:
            raise ValueError("uncertainty no puede asignar action.")
        if payload.get("conviction") is not None:
            raise ValueError("uncertainty no puede publicar convicción.")

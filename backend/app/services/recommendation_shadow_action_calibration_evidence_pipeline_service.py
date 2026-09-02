from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.services.recommendation_shadow_action_calibration_evidence_service import (
    RecommendationShadowActionCalibrationEvidenceService,
)
from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)


class _SplitService(Protocol):
    def build(
        self,
        *,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]: ...


class _EvidenceService(Protocol):
    def assess(self, split: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionCalibrationEvidencePipelineService:
    """Connect real live PIT evidence to the calibration evidence gate.

    The split producer remains the only source of partition rows. The evidence
    service then independently revalidates that split before measuring it. This
    pipeline intentionally exposes no alternative path that accepts caller-built
    train/validation rows and never consumes the future reserve.
    """

    def __init__(
        self,
        *,
        split_service: _SplitService | None = None,
        evidence_service: _EvidenceService | None = None,
    ) -> None:
        self._split_service = split_service or RecommendationShadowActionCalibrationSplitService()
        self._evidence_service = evidence_service or RecommendationShadowActionCalibrationEvidenceService()

    def evaluate(
        self,
        *,
        train_end: datetime,
        validation_end: datetime,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int] = (7, 30, 90, 180, 365),
    ) -> dict[str, Any]:
        split = self._split_service.build(
            train_end=train_end,
            validation_end=validation_end,
            as_of=as_of,
            symbol=symbol,
            horizons=horizons,
        )
        evidence = self._evidence_service.assess(split)
        self._assert_shadow_output(split=split, evidence=evidence)
        return evidence

    def _assert_shadow_output(
        self,
        *,
        split: dict[str, Any],
        evidence: dict[str, Any],
    ) -> None:
        if not isinstance(split, dict) or not isinstance(evidence, dict):
            raise ValueError("El pipeline de evidencia shadow recibió un artefacto inválido.")
        if evidence.get("sourceSplitFingerprint") != split.get("splitFingerprint"):
            raise ValueError("La evidencia no corresponde al split producido por el pipeline.")
        for payload, name in ((split, "split"), (evidence, "evidence")):
            if payload.get("advisoryStatus") != "no_advice":
                raise ValueError(f"{name} violó advisoryStatus=no_advice.")
            if payload.get("productionEligible") is not False:
                raise ValueError(f"{name} intentó habilitar producción.")
            if payload.get("recommendationCandidateReady") is not False:
                raise ValueError(f"{name} intentó habilitar recomendaciones.")
            if payload.get("actionThresholdCalibrationResearchEligible") is not False:
                raise ValueError(f"{name} intentó promover calibración automáticamente.")
            if payload.get("action") is not None:
                raise ValueError(f"{name} no puede asignar una acción.")
            if payload.get("score") is not None or payload.get("conviction") is not None:
                raise ValueError(f"{name} no puede publicar score/conviction.")
            if payload.get("actionThresholds") is not None:
                raise ValueError(f"{name} no puede publicar thresholds.")

        split_policy = split.get("policy")
        evidence_policy = evidence.get("policy")
        if not isinstance(split_policy, dict) or split_policy.get("futureReserveConsumed") is not False:
            raise ValueError("El split consumió la reserva temporal futura.")
        if not isinstance(evidence_policy, dict) or evidence_policy.get("futureReserveConsumed") is not False:
            raise ValueError("La evidencia consumió la reserva temporal futura.")
        if evidence_policy.get("thresholdFitting") != "not_performed":
            raise ValueError("La evidencia ajustó thresholds antes del contrato económico.")
        if evidence_policy.get("automaticProductionPromotion") is not False:
            raise ValueError("La evidencia no puede promover producción automáticamente.")
        if evidence_policy.get("automaticTrading") is not False:
            raise ValueError("La evidencia no puede habilitar trading automático.")

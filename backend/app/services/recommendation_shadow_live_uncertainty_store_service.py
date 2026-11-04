from __future__ import annotations

from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_live_uncertainty_repository import (
    RecommendationShadowLiveUncertaintyRepository,
)


class _CandidateRepository(Protocol):
    def get(self, candidate_id: int) -> dict[str, Any] | None: ...


class _UncertaintyRepository(Protocol):
    def save(
        self,
        *,
        candidate_id: int,
        candidate_fingerprint: str,
        artifact_version: str,
        artifact: dict[str, Any],
    ) -> int: ...

    def get(self, uncertainty_id: int) -> dict[str, Any] | None: ...


class RecommendationShadowLiveUncertaintyStoreService:
    """Fail-closed persistence boundary for empirical uncertainty artifacts."""

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        uncertainty_repository: _UncertaintyRepository | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._uncertainty_repository = (
            uncertainty_repository or RecommendationShadowLiveUncertaintyRepository()
        )

    def store(self, *, candidate_id: int, uncertainty: dict[str, Any]) -> dict[str, Any]:
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        self._assert_shadow_contract(uncertainty)
        artifact_candidate_id = uncertainty.get("candidateId")
        if artifact_candidate_id != candidate_id:
            raise ValueError("La incertidumbre no pertenece al candidate_id solicitado.")
        artifact_version = self._required_text(
            uncertainty.get("artifactVersion"), "artifactVersion"
        )
        candidate_fingerprint = self._sha256_text(
            uncertainty.get("candidateFingerprint"), "candidateFingerprint"
        )

        stored_candidate = self._candidate_repository.get(candidate_id)
        if stored_candidate is None:
            raise ValueError("No existe el candidato live que ancla la incertidumbre.")
        stored_candidate_fingerprint = self._sha256_text(
            stored_candidate.get("candidate_fingerprint"),
            "stored.candidate_fingerprint",
        )
        if candidate_fingerprint != stored_candidate_fingerprint:
            raise ValueError("La incertidumbre cambió la identidad del candidato persistido.")

        uncertainty_id = self._uncertainty_repository.save(
            candidate_id=candidate_id,
            candidate_fingerprint=candidate_fingerprint,
            artifact_version=artifact_version,
            artifact=uncertainty,
        )
        loaded = self._uncertainty_repository.get(uncertainty_id)
        if loaded is None:
            raise RuntimeError("No se pudo releer la incertidumbre recién persistida.")
        if loaded.get("candidate_id") != candidate_id:
            raise RuntimeError("La incertidumbre persistida cambió candidate_id.")
        if loaded.get("candidate_fingerprint") != candidate_fingerprint:
            raise RuntimeError("La incertidumbre persistida cambió candidateFingerprint.")
        loaded_artifact = loaded.get("artifact")
        if loaded_artifact != uncertainty:
            raise RuntimeError("La incertidumbre persistida cambió su artefacto.")
        uncertainty_fingerprint = self._sha256_text(
            loaded.get("uncertainty_fingerprint"), "uncertainty_fingerprint"
        )
        return {
            "status": "shadow_live_uncertainty_persisted",
            "uncertaintyId": uncertainty_id,
            "candidateId": candidate_id,
            "candidateFingerprint": candidate_fingerprint,
            "uncertaintyFingerprint": uncertainty_fingerprint,
            "artifactVersion": artifact_version,
            "calibratedHorizonCount": uncertainty.get("calibratedHorizonCount", 0),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "action": None,
            "conviction": None,
        }

    def _assert_shadow_contract(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("uncertainty debe ser un objeto.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La incertidumbre debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La incertidumbre debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("La incertidumbre no puede habilitar recomendaciones.")
        if payload.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("La incertidumbre no puede promover calibración de acciones.")
        if payload.get("action") is not None:
            raise ValueError("La incertidumbre no puede asignar action.")
        if payload.get("conviction") is not None:
            raise ValueError("La incertidumbre no puede publicar conviction.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("La incertidumbre debe declarar policy.")
        if policy.get("cutoff") != "candidate_as_of_not_request_time":
            raise ValueError("La incertidumbre debe estar cortada en candidate.asOf.")
        if policy.get("automaticModelMutation") is not False:
            raise ValueError("La incertidumbre no puede mutar modelos automáticamente.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("La incertidumbre no puede promover producción automáticamente.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("La incertidumbre no puede habilitar trading automático.")

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _sha256_text(self, value: object, field: str) -> str:
        normalized = self._required_text(value, field).lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return normalized

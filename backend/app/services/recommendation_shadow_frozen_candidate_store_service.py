from __future__ import annotations

from typing import Any

from app.repositories.recommendation_shadow_frozen_candidate_repository import (
    RecommendationShadowFrozenCandidateRepository,
)
from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)


class RecommendationShadowFrozenCandidateStoreService:
    """Validate and persist research-only frozen candidates atomically by identity."""

    def __init__(
        self,
        *,
        repository: RecommendationShadowFrozenCandidateRepository | None = None,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
    ) -> None:
        self._repository = repository or RecommendationShadowFrozenCandidateRepository()
        self._gated_freeze_service = gated_freeze_service or RecommendationShadowGatedFreezeService()

    def persist(self, *, bundle: dict[str, Any]) -> dict[str, Any]:
        validated = self._gated_freeze_service.validate_bundle(bundle)
        self._assert_shadow(validated)
        artifact_id = self._repository.save(bundle=validated)
        persisted = self._repository.get_by_fingerprint(validated["bundleFingerprint"])
        if persisted is None or int(persisted.get("id", -1)) != artifact_id:
            raise RuntimeError("El frozen candidate persistido no puede recuperarse de forma íntegra.")
        stored_bundle = persisted.get("bundle")
        if not isinstance(stored_bundle, dict):
            raise RuntimeError("El frozen candidate persistido no conserva el bundle completo.")
        if stored_bundle.get("bundleFingerprint") != validated.get("bundleFingerprint"):
            raise RuntimeError("El frozen candidate recuperado cambió de fingerprint.")

        return {
            "status": "shadow_frozen_candidate_persisted",
            "artifactId": artifact_id,
            "bundleFingerprint": validated["bundleFingerprint"],
            "modelFingerprint": validated["modelFingerprint"],
            "horizonDays": int(validated["horizonDays"]),
            "researchCutoff": validated["researchCutoff"],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "gatedBundleValidationBeforeWrite": True,
                "separateFromRecommendationHistory": True,
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
            },
        }

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError("El bundle validado violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El bundle validado violó advisoryStatus=no_advice.")

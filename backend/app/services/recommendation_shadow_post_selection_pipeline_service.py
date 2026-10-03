from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_post_selection_repository import (
    RecommendationShadowPostSelectionRepository,
)
from app.services.recommendation_shadow_independent_holdout_service import (
    RecommendationShadowIndependentHoldoutService,
)
from app.services.recommendation_shadow_post_selection_confirmation_service import (
    RecommendationShadowPostSelectionConfirmationService,
)


class RecommendationShadowPostSelectionPipelineService:
    """Commit selection first, then evaluate only evidence after that boundary."""

    def __init__(
        self,
        *,
        repository: RecommendationShadowPostSelectionRepository | None = None,
        frozen_model_service: RecommendationShadowIndependentHoldoutService | None = None,
        confirmation_service: RecommendationShadowPostSelectionConfirmationService | None = None,
    ) -> None:
        self._repository = repository or RecommendationShadowPostSelectionRepository()
        self._frozen_model_service = frozen_model_service or RecommendationShadowIndependentHoldoutService()
        self._confirmation_service = confirmation_service or RecommendationShadowPostSelectionConfirmationService(
            frozen_model_service=self._frozen_model_service
        )

    def register_selection(
        self,
        *,
        frozen_model: dict[str, Any],
        selected_at: datetime,
    ) -> dict[str, Any]:
        selected = self._aware_utc(selected_at, "selected_at")
        model = self._frozen_model_service._validated_model(frozen_model)
        record = self._repository.register(frozen_model=model, selected_at=selected)
        validated = self._repository.validate_record(record)
        if validated.get("model_fingerprint") != model.get("fingerprint"):
            raise ValueError("La selección persistida no corresponde al modelo validado.")
        return {
            "status": "shadow_post_selection_registered",
            "selectionId": int(validated["id"]),
            "selectionFingerprint": validated["selection_fingerprint"],
            "modelFingerprint": validated["model_fingerprint"],
            "researchCutoff": validated["research_cutoff"],
            "horizonDays": int(validated["horizon_days"]),
            "confirmationStart": validated["selected_at"],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": {
                "selectionBoundary": "first_persisted_selection_is_immutable",
                "backdatingAfterEvidence": False,
                "actions": "not_assigned",
                "automaticProductionPromotion": False,
            },
        }

    def evaluate_registered_selection(
        self,
        *,
        model_fingerprint: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        record = self._repository.get(model_fingerprint=model_fingerprint)
        if record is None:
            return {
                "status": "shadow_post_selection_not_registered",
                "modelFingerprint": str(model_fingerprint or "").strip(),
                "asOf": cutoff.isoformat(),
                "postSelectionConfirmationEvidenceReady": False,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "policy": {
                    "unregisteredConfirmation": "blocked",
                    "actions": "not_assigned",
                    "automaticProductionPromotion": False,
                },
            }
        validated = self._repository.validate_record(record)
        model = validated.get("frozen_model")
        if not isinstance(model, dict):
            raise ValueError("La selección persistida no contiene frozen_model.")
        model = self._frozen_model_service._validated_model(model)
        if model.get("fingerprint") != validated.get("model_fingerprint"):
            raise ValueError("El modelo persistido cambió de fingerprint.")
        start = self._parse_utc(validated.get("selected_at"), "selected_at")
        result = self._confirmation_service.evaluate(
            frozen_model=model,
            confirmation_start=start,
            as_of=cutoff,
        )
        self._assert_shadow(result)
        return {
            **result,
            "selectionId": int(validated["id"]),
            "selectionFingerprint": validated["selection_fingerprint"],
            "selectionBoundaryPersisted": True,
        }

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError("La confirmación post-selection violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La confirmación post-selection violó advisoryStatus=no_advice.")

    def _parse_utc(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

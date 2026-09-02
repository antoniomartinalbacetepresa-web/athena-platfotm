from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from app.repositories.recommendation_shadow_action_threshold_selection_repository import (
    RecommendationShadowActionThresholdSelectionRepository,
)
from app.services.recommendation_shadow_action_threshold_selection_service import (
    RecommendationShadowActionThresholdSelectionService,
)


class _SelectionService(Protocol):
    def select(self, utility_panel: dict[str, Any]) -> dict[str, Any]: ...


class _SelectionRepository(Protocol):
    def register(
        self,
        *,
        selection: dict[str, Any],
        selected_at: datetime,
    ) -> dict[str, Any]: ...

    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowActionThresholdFreezeService:
    """Select validation policies and commit them before any future confirmation.

    A successful selection is persisted immediately. Repeated calls for the same
    selection recover the first immutable timestamp instead of allowing the caller
    to move the future-confirmation boundary after outcomes have become visible.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-freeze-v1"

    def __init__(
        self,
        *,
        selection_service: _SelectionService | None = None,
        selection_repository: _SelectionRepository | None = None,
    ) -> None:
        self._selection_service = (
            selection_service or RecommendationShadowActionThresholdSelectionService()
        )
        self._selection_repository = (
            selection_repository
            or RecommendationShadowActionThresholdSelectionRepository()
        )

    def freeze(
        self,
        *,
        utility_panel: dict[str, Any],
        selected_at: datetime,
    ) -> dict[str, Any]:
        selection = self._selection_service.select(utility_panel)
        self._assert_shadow_selection(selection)

        if selection.get("futureReserveConfirmationEligible") is not True:
            return {
                "status": "shadow_action_threshold_freeze_insufficient",
                "artifactVersion": self.ARTIFACT_VERSION,
                "selectionFingerprint": selection.get("selectionFingerprint"),
                "registered": False,
                "selectedAt": None,
                "registrationFingerprint": None,
                "futureReserveConfirmationEligible": False,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "recommendationCandidateReady": False,
                "action": None,
                "score": None,
                "conviction": None,
                "policy": self._policy(),
            }

        record = self._selection_repository.register(
            selection=selection,
            selected_at=selected_at,
        )
        if self._selection_repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó el registro de thresholds.")

        selection_fingerprint = self._sha256(
            selection.get("selectionFingerprint"), "selectionFingerprint"
        )
        if record.get("selection_fingerprint") != selection_fingerprint:
            raise ValueError("El registro no corresponde a la selección recién congelada.")
        persisted_selection = record.get("selection")
        if not isinstance(persisted_selection, dict):
            raise ValueError("El registro persistido carece de selección válida.")
        if persisted_selection.get("selectionFingerprint") != selection_fingerprint:
            raise ValueError("La selección persistida cambió su fingerprint.")

        reloaded = self._selection_repository.get(
            selection_fingerprint=selection_fingerprint
        )
        if reloaded is None:
            raise RuntimeError("No se pudo volver a cargar la selección congelada.")
        if self._selection_repository.validate_record(reloaded) is not reloaded:
            raise ValueError("El repositorio sustituyó la selección recargada.")
        if reloaded.get("registration_fingerprint") != record.get(
            "registration_fingerprint"
        ):
            raise ValueError("La selección cambió después de persistirse.")
        if reloaded.get("selected_at") != record.get("selected_at"):
            raise ValueError("La frontera temporal cambió después de persistirse.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "selectionFingerprint": selection_fingerprint,
            "registrationFingerprint": self._sha256(
                record.get("registration_fingerprint"),
                "registrationFingerprint",
            ),
            "selectedAt": record.get("selected_at"),
        }
        return {
            "status": "shadow_action_thresholds_frozen_before_future_confirmation",
            **core,
            "freezeFingerprint": self._fingerprint(core),
            "registered": True,
            "futureReserveConfirmationEligible": True,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": self._policy(),
        }

    def _assert_shadow_selection(self, selection: dict[str, Any]) -> None:
        if not isinstance(selection, dict):
            raise ValueError("La selección de thresholds debe ser un objeto.")
        if selection.get("advisoryStatus") != "no_advice":
            raise ValueError("La selección debe mantener advisoryStatus=no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if selection.get(field) is not False:
                raise ValueError(f"La selección intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if selection.get(field) is not None:
                raise ValueError(f"La selección no puede publicar {field}.")
        policy = selection.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("La selección carece de policy válida.")
        if policy.get("candidateSelectionPartition") != "validation_only":
            raise ValueError("La selección no procede exclusivamente de validation.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("La reserva futura ya fue consumida antes del freeze.")
        if policy.get("selectedResearchThresholdsMayBeRefitOnFutureReserve") is not False:
            raise ValueError("La selección permite refit indebido sobre la reserva futura.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("La selección habilitó promoción automática.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("La selección habilitó trading automático.")

    def _policy(self) -> dict[str, Any]:
        return {
            "selectionSource": "validation_only_after_train_only_candidate_generation",
            "firstSelectionBoundary": "sqlite_persisted_immutable",
            "futureEvidenceBeforeSelectedAtMayBeUsed": False,
            "futureReserveMayRefitThresholds": False,
            "futureReserveMayReselectPolicies": False,
            "futureReserveConsumed": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

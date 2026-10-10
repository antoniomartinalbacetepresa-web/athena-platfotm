from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

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

    The operational freeze timestamp comes from the service clock, never from the
    caller. This prevents backdating the selection boundary after validation labels
    have already been observed. Repeated calls recover the first persisted boundary.
    The selected policy is also cryptographically bound to the exact utility panel
    supplied to this freeze, preventing cross-panel substitution.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-freeze-v3"

    def __init__(
        self,
        *,
        selection_service: _SelectionService | None = None,
        selection_repository: _SelectionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._selection_service = (
            selection_service or RecommendationShadowActionThresholdSelectionService()
        )
        self._selection_repository = (
            selection_repository
            or RecommendationShadowActionThresholdSelectionRepository()
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def freeze(
        self,
        *,
        utility_panel: dict[str, Any],
    ) -> dict[str, Any]:
        panel_fingerprint = self._sha256(
            utility_panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
        )
        selection = self._selection_service.select(utility_panel)
        self._assert_shadow_selection(
            selection,
            expected_panel_fingerprint=panel_fingerprint,
        )

        if selection.get("futureReserveConfirmationEligible") is not True:
            return {
                "status": "shadow_action_threshold_freeze_insufficient",
                "artifactVersion": self.ARTIFACT_VERSION,
                "sourceUtilityPanelFingerprint": panel_fingerprint,
                "selectionFingerprint": selection.get("selectionFingerprint"),
                "registered": False,
                "selectedAt": None,
                "registrationFingerprint": None,
                "futureReserveConfirmationEligible": False,
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

        selected_at = self._clock_now()
        self._assert_not_backdated(
            utility_panel=utility_panel,
            selected_at=selected_at,
        )
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
        if persisted_selection.get("sourceUtilityPanelFingerprint") != panel_fingerprint:
            raise ValueError("La selección persistida cambió de panel de utilidad.")

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
        reloaded_selection = reloaded.get("selection")
        if not isinstance(reloaded_selection, dict):
            raise ValueError("La selección recargada carece de payload válido.")
        if reloaded_selection.get("sourceUtilityPanelFingerprint") != panel_fingerprint:
            raise ValueError("La selección recargada ya no pertenece al panel congelado.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "sourceUtilityPanelFingerprint": panel_fingerprint,
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

    def _assert_not_backdated(
        self,
        *,
        utility_panel: dict[str, Any],
        selected_at: datetime,
    ) -> None:
        rows = utility_panel.get("validationUtilityRows")
        if not isinstance(rows, list) or not rows:
            raise ValueError(
                "Un freeze elegible requiere validationUtilityRows para verificar la frontera temporal."
            )
        latest_observed: datetime | None = None
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("validationUtilityRows contiene una fila inválida.")
            evaluated_at = self._parse_aware(
                row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
            )
            if latest_observed is None or evaluated_at > latest_observed:
                latest_observed = evaluated_at
        if latest_observed is None:
            raise ValueError("No se pudo determinar la última evidencia de validation.")
        if selected_at < latest_observed:
            raise ValueError(
                "El reloj de freeze es anterior a evidencia de validation ya observada."
            )

    def _assert_shadow_selection(
        self,
        selection: dict[str, Any],
        *,
        expected_panel_fingerprint: str,
    ) -> None:
        if not isinstance(selection, dict):
            raise ValueError("La selección de thresholds debe ser un objeto.")
        source_panel = self._sha256(
            selection.get("sourceUtilityPanelFingerprint"),
            "sourceUtilityPanelFingerprint",
        )
        if source_panel != expected_panel_fingerprint:
            raise ValueError("La selección de thresholds no pertenece al panel suministrado.")
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
            "selectionBoundToUtilityPanelFingerprint": True,
            "firstSelectionBoundary": "service_clock_then_sqlite_persisted_immutable",
            "callerSuppliedSelectionTimestampAccepted": False,
            "freezeTimestampMustNotPrecedeObservedValidationEvidence": True,
            "futureEvidenceBeforeSelectedAtMayBeUsed": False,
            "futureReserveMayRefitThresholds": False,
            "futureReserveMayReselectPolicies": False,
            "futureReserveConsumed": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _clock_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("El reloj de freeze debe devolver datetime con zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

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

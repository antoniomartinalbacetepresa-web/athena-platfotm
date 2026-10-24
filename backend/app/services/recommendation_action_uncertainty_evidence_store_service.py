from __future__ import annotations

from typing import Any, Protocol

from app.repositories.recommendation_action_uncertainty_evidence_repository import (
    RecommendationActionUncertaintyEvidenceRepository,
)
from app.repositories.recommendation_shadow_action_threshold_confirmation_repository import (
    RecommendationShadowActionThresholdConfirmationRepository,
)
from app.services.recommendation_action_uncertainty_evidence_service import (
    RecommendationActionUncertaintyEvidenceService,
)


class _ConfirmationRepository(Protocol):
    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _Evaluator(Protocol):
    def evaluate_registered(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
        economic_contract: dict[str, Any],
        symbol: str | None = None,
    ) -> dict[str, Any]: ...


class _EvidenceRepository(Protocol):
    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationActionUncertaintyEvidenceStoreService:
    """Derive and seal uncertainty only from the first persisted OOS confirmation.

    The diagnostic evaluator can still validate a supplied confirmation in research
    code. This authority-producing path cannot: it resolves the immutable first seal
    from backend persistence, evaluates that exact artifact, and only then persists
    the resulting uncertainty evidence for downstream action/allocation use.
    """

    def __init__(
        self,
        *,
        confirmation_repository: _ConfirmationRepository | None = None,
        evaluator: _Evaluator | None = None,
        evidence_repository: _EvidenceRepository | None = None,
    ) -> None:
        self._confirmation_repository = (
            confirmation_repository
            or RecommendationShadowActionThresholdConfirmationRepository()
        )
        self._evaluator = evaluator or RecommendationActionUncertaintyEvidenceService()
        self._evidence_repository = (
            evidence_repository or RecommendationActionUncertaintyEvidenceRepository()
        )

    def evaluate_persisted_and_seal(
        self,
        *,
        selection_fingerprint: str,
        protocol_id: str,
        economic_contract: dict[str, Any],
        symbol: str | None = None,
    ) -> dict[str, Any]:
        record = self._confirmation_repository.get(
            selection_fingerprint=selection_fingerprint
        )
        if record is None:
            raise ValueError("La confirmación OOS requerida no está persistida.")
        if self._confirmation_repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó la confirmación OOS persistida.")
        confirmation = record.get("confirmation")
        if not isinstance(confirmation, dict):
            raise ValueError("El registro OOS carece de confirmación válida.")
        if confirmation.get("selectionFingerprint") != selection_fingerprint:
            raise ValueError("La confirmación OOS persistida cambió de selección.")

        artifact = self._evaluator.evaluate_registered(
            confirmation_artifact=confirmation,
            protocol_id=protocol_id,
            economic_contract=economic_contract,
            symbol=symbol,
        )
        if not isinstance(artifact, dict):
            raise ValueError("El evaluador no devolvió evidencia de incertidumbre válida.")
        if artifact.get("confirmationFingerprint") != confirmation.get(
            "confirmationFingerprint"
        ):
            raise ValueError("La incertidumbre derivada cambió la confirmación OOS.")
        if artifact.get("selectionFingerprint") != selection_fingerprint:
            raise ValueError("La incertidumbre derivada cambió la selección congelada.")

        persisted_record = self._evidence_repository.seal(artifact=artifact)
        if not isinstance(persisted_record, dict):
            raise ValueError("El repositorio no devolvió un registro de incertidumbre válido.")
        if self._evidence_repository.validate_record(persisted_record) is not persisted_record:
            raise ValueError("El repositorio sustituyó la evidencia de incertidumbre sellada.")
        persisted = persisted_record.get("artifact")
        if not isinstance(persisted, dict) or persisted != artifact:
            raise ValueError("La evidencia persistida difiere de la derivada por backend.")

        return {
            "status": "action_uncertainty_evidence_sealed_non_advisory",
            "evidence": persisted,
            "evidenceFingerprint": persisted_record.get("evidence_fingerprint"),
            "recordFingerprint": persisted_record.get("record_fingerprint"),
            "persistedAt": persisted_record.get("persisted_at"),
            "sourceConfirmationRepositoryFingerprint": record.get(
                "confirmation_fingerprint"
            ),
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

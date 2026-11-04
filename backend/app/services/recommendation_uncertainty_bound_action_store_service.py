from __future__ import annotations

from typing import Any, Protocol

from app.repositories.recommendation_action_uncertainty_evidence_repository import (
    RecommendationActionUncertaintyEvidenceRepository,
)
from app.repositories.recommendation_uncertainty_bound_action_candidate_repository import (
    RecommendationUncertaintyBoundActionCandidateRepository,
)
from app.services.recommendation_uncertainty_bound_action_candidate_service import (
    RecommendationUncertaintyBoundActionCandidateService,
)


class _Builder(Protocol):
    def build(
        self,
        *,
        validated_action_candidate: dict[str, Any],
        uncertainty_evidence: dict[str, Any],
    ) -> dict[str, Any]: ...


class _EvidenceRepository(Protocol):
    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _Repository(Protocol):
    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationUncertaintyBoundActionStoreService:
    """Build and append-only seal an action from persisted uncertainty authority only.

    Allocation authority must never originate from a caller-supplied uncertainty JSON.
    The caller supplies only the fingerprint of an uncertainty artifact previously
    sealed by the backend. This service resolves and validates that immutable record,
    builds the exact action candidate, seals it, and exposes both persistence
    fingerprints so downstream allocation can prove the full authority chain.
    """

    def __init__(
        self,
        *,
        builder: _Builder | None = None,
        evidence_repository: _EvidenceRepository | None = None,
        repository: _Repository | None = None,
    ) -> None:
        self._builder = builder or RecommendationUncertaintyBoundActionCandidateService()
        self._evidence_repository = (
            evidence_repository or RecommendationActionUncertaintyEvidenceRepository()
        )
        self._repository = (
            repository or RecommendationUncertaintyBoundActionCandidateRepository()
        )

    def build_and_seal(
        self,
        *,
        validated_action_candidate: dict[str, Any],
        uncertainty_evidence_fingerprint: str,
    ) -> dict[str, Any]:
        evidence_record = self._evidence_repository.get(
            evidence_fingerprint=uncertainty_evidence_fingerprint
        )
        if evidence_record is None:
            raise ValueError("La evidencia de incertidumbre requerida no está sellada.")
        if self._evidence_repository.validate_record(evidence_record) is not evidence_record:
            raise ValueError("El repositorio sustituyó la evidencia de incertidumbre sellada.")
        evidence = evidence_record.get("artifact")
        if not isinstance(evidence, dict):
            raise ValueError("El registro de incertidumbre carece de artefacto válido.")
        if evidence.get("actionUncertaintyEvidenceFingerprint") != evidence_record.get(
            "evidence_fingerprint"
        ):
            raise ValueError("El registro de incertidumbre cambió el fingerprint del artefacto.")
        if evidence_record.get("evidence_fingerprint") != uncertainty_evidence_fingerprint:
            raise ValueError("La evidencia resuelta no coincide con el fingerprint solicitado.")

        artifact = self._builder.build(
            validated_action_candidate=validated_action_candidate,
            uncertainty_evidence=evidence,
        )
        if not isinstance(artifact, dict):
            raise ValueError("El builder no devolvió un candidato de acción válido.")
        if artifact.get("actionUncertaintyEvidenceFingerprint") != evidence_record.get(
            "evidence_fingerprint"
        ):
            raise ValueError("El candidato de acción cambió la evidencia de incertidumbre.")

        record = self._repository.seal(artifact=artifact)
        if not isinstance(record, dict):
            raise ValueError("El repositorio no devolvió un registro de acción válido.")
        if self._repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó el registro de acción sellado.")
        persisted = record.get("artifact")
        if not isinstance(persisted, dict) or persisted != artifact:
            raise ValueError("El candidato de acción persistido difiere del derivado por backend.")
        return {
            "status": "uncertainty_bound_action_candidate_sealed_non_advisory",
            "candidate": persisted,
            "candidateFingerprint": record.get("candidate_fingerprint"),
            "recordFingerprint": record.get("record_fingerprint"),
            "persistedAt": record.get("persisted_at"),
            "sourceUncertaintyEvidenceFingerprint": evidence_record.get(
                "evidence_fingerprint"
            ),
            "sourceUncertaintyRecordFingerprint": evidence_record.get(
                "record_fingerprint"
            ),
            "sourceUncertaintyPersistedAt": evidence_record.get("persisted_at"),
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

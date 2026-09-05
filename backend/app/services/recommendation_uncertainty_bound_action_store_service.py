from __future__ import annotations

from typing import Any, Protocol

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


class _Repository(Protocol):
    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationUncertaintyBoundActionStoreService:
    """Build and append-only seal the exact backend-derived action candidate.

    This is the authority-producing path for allocation. A caller cannot promote an
    arbitrary action JSON merely by recomputing its artifact fingerprint: allocation
    later resolves the candidate from the append-only repository by fingerprint.
    """

    def __init__(
        self,
        *,
        builder: _Builder | None = None,
        repository: _Repository | None = None,
    ) -> None:
        self._builder = builder or RecommendationUncertaintyBoundActionCandidateService()
        self._repository = (
            repository or RecommendationUncertaintyBoundActionCandidateRepository()
        )

    def build_and_seal(
        self,
        *,
        validated_action_candidate: dict[str, Any],
        uncertainty_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        artifact = self._builder.build(
            validated_action_candidate=validated_action_candidate,
            uncertainty_evidence=uncertainty_evidence,
        )
        if not isinstance(artifact, dict):
            raise ValueError("El builder no devolvió un candidato de acción válido.")
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
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

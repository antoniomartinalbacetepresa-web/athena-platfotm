from __future__ import annotations

import copy

import pytest

from app.services.recommendation_uncertainty_bound_action_store_service import (
    RecommendationUncertaintyBoundActionStoreService,
)


EVIDENCE_FP = "a" * 64
EVIDENCE_RECORD_FP = "b" * 64
ACTION_FP = "c" * 64
ACTION_RECORD_FP = "d" * 64


class _EvidenceRepository:
    def __init__(self, record=None, *, substitute=False):
        self.record = record
        self.substitute = substitute

    def get(self, *, evidence_fingerprint):
        if self.record is None:
            return None
        if self.record.get("evidence_fingerprint") != evidence_fingerprint:
            return None
        return self.record

    def validate_record(self, record):
        return copy.deepcopy(record) if self.substitute else record


class _Builder:
    def __init__(self, *, mutate_evidence=False):
        self.mutate_evidence = mutate_evidence
        self.calls = 0

    def build(self, *, validated_action_candidate, uncertainty_evidence):
        self.calls += 1
        fingerprint = (
            "9" * 64
            if self.mutate_evidence
            else uncertainty_evidence["actionUncertaintyEvidenceFingerprint"]
        )
        return {
            "artifactVersion": "test-action-v1",
            "action": "hold",
            "actionUncertaintyEvidenceFingerprint": fingerprint,
            "sourceCandidate": copy.deepcopy(validated_action_candidate),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }


class _ActionRepository:
    def __init__(self, *, substitute=False, mutate_artifact=False):
        self.substitute = substitute
        self.mutate_artifact = mutate_artifact
        self.seal_calls = 0

    def seal(self, *, artifact):
        self.seal_calls += 1
        persisted = copy.deepcopy(artifact)
        if self.mutate_artifact:
            persisted["action"] = "buy"
        return {
            "artifact": persisted,
            "candidate_fingerprint": ACTION_FP,
            "record_fingerprint": ACTION_RECORD_FP,
            "persisted_at": "2026-09-05T12:00:00+00:00",
        }

    def validate_record(self, record):
        return copy.deepcopy(record) if self.substitute else record


def _evidence_record():
    return {
        "evidence_fingerprint": EVIDENCE_FP,
        "record_fingerprint": EVIDENCE_RECORD_FP,
        "persisted_at": "2026-09-05T11:00:00+00:00",
        "artifact": {
            "artifactVersion": "athena-action-uncertainty-evidence-v1",
            "actionUncertaintyEvidenceFingerprint": EVIDENCE_FP,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "action": None,
            "allocation": None,
        },
    }


def test_action_store_resolves_persisted_uncertainty_by_fingerprint_only():
    action_repository = _ActionRepository()
    service = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(),
        evidence_repository=_EvidenceRepository(_evidence_record()),
        repository=action_repository,
    )

    result = service.build_and_seal(
        validated_action_candidate={"status": "validated", "action": "hold"},
        uncertainty_evidence_fingerprint=EVIDENCE_FP,
    )

    assert result["sourceUncertaintyEvidenceFingerprint"] == EVIDENCE_FP
    assert result["sourceUncertaintyRecordFingerprint"] == EVIDENCE_RECORD_FP
    assert result["candidate"]["actionUncertaintyEvidenceFingerprint"] == EVIDENCE_FP
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False
    assert action_repository.seal_calls == 1


def test_unknown_uncertainty_fingerprint_fails_closed_before_building_action():
    builder = _Builder()
    service = RecommendationUncertaintyBoundActionStoreService(
        builder=builder,
        evidence_repository=_EvidenceRepository(None),
        repository=_ActionRepository(),
    )

    with pytest.raises(ValueError, match="no está sellada"):
        service.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )

    assert builder.calls == 0


def test_substituted_uncertainty_record_fails_closed():
    service = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(),
        evidence_repository=_EvidenceRepository(_evidence_record(), substitute=True),
        repository=_ActionRepository(),
    )

    with pytest.raises(ValueError, match="sustituyó la evidencia"):
        service.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )


def test_uncertainty_record_artifact_fingerprint_mismatch_fails_closed():
    record = _evidence_record()
    record["artifact"]["actionUncertaintyEvidenceFingerprint"] = "9" * 64
    service = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(),
        evidence_repository=_EvidenceRepository(record),
        repository=_ActionRepository(),
    )

    with pytest.raises(ValueError, match="cambió el fingerprint"):
        service.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )


def test_builder_cannot_rebind_action_to_different_uncertainty_evidence():
    service = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(mutate_evidence=True),
        evidence_repository=_EvidenceRepository(_evidence_record()),
        repository=_ActionRepository(),
    )

    with pytest.raises(ValueError, match="cambió la evidencia"):
        service.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )


def test_action_repository_substitution_or_mutation_fails_closed():
    substituted = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(),
        evidence_repository=_EvidenceRepository(_evidence_record()),
        repository=_ActionRepository(substitute=True),
    )
    with pytest.raises(ValueError, match="sustituyó el registro de acción"):
        substituted.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )

    mutated = RecommendationUncertaintyBoundActionStoreService(
        builder=_Builder(),
        evidence_repository=_EvidenceRepository(_evidence_record()),
        repository=_ActionRepository(mutate_artifact=True),
    )
    with pytest.raises(ValueError, match="difiere del derivado"):
        mutated.build_and_seal(
            validated_action_candidate={"status": "validated"},
            uncertainty_evidence_fingerprint=EVIDENCE_FP,
        )

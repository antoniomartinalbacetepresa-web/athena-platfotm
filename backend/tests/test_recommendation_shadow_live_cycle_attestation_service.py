from __future__ import annotations

import hashlib
import json

import pytest

from app.services.recommendation_shadow_live_cycle_attestation_service import (
    RecommendationShadowLiveCycleAttestationService,
)


class FakeRepository:
    def __init__(self) -> None:
        self.rows = {}
        self.next_id = 1

    def save(self, *, candidate_id, candidate_fingerprint, artifact_version, artifact):
        canonical = json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        existing = self.rows.get(candidate_id)
        if existing is not None:
            if existing["artifact_json"] != canonical:
                raise ValueError("El candidato live ya tiene una atestación de ciclo distinta.")
            return existing["id"]
        row = {
            "id": self.next_id,
            "candidate_id": candidate_id,
            "candidate_fingerprint": candidate_fingerprint,
            "attestation_fingerprint": fingerprint,
            "artifact_version": artifact_version,
            "artifact_json": canonical,
            "artifact": json.loads(canonical),
        }
        self.rows[candidate_id] = row
        self.next_id += 1
        return row["id"]

    def get_for_candidate(self, candidate_id):
        row = self.rows.get(candidate_id)
        return None if row is None else dict(row)


def _cycle() -> dict:
    bundle = "a" * 64
    candidate = "c" * 64
    uncertainty = "e" * 64
    decision = "f" * 64
    return {
        "status": "shadow_live_cycle_persisted",
        "candidateId": 20,
        "snapshotId": 10,
        "candidateFingerprint": candidate,
        "confirmationEvidenceFingerprint": "d" * 64,
        "uncertaintyFingerprint": uncertainty,
        "decisionResearchFingerprint": decision,
        "symbol": "TEST",
        "asOf": "2026-09-01T12:00:00+00:00",
        "benchmarkSymbol": "SPY",
        "bundleFingerprints": [bundle],
        "frozenCandidateSource": "sqlite_persisted_and_revalidated",
        "candidate": {
            "candidateFingerprint": candidate,
            "horizons": {
                "30": {
                    "horizonDays": 30,
                    "bundleFingerprint": bundle,
                }
            },
        },
        "decisionResearch": {
            "candidateFingerprint": candidate,
            "uncertaintyFingerprint": uncertainty,
            "decisionResearchFingerprint": decision,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "policy": {
            "callerSuppliedFrozenBundleJsonTrusted": False,
            "frozenBundleIntegrity": "gated_freeze_revalidated_after_load",
        },
    }


def test_attestation_is_deterministic_idempotent_and_shadow_only():
    repository = FakeRepository()
    service = RecommendationShadowLiveCycleAttestationService(repository=repository)

    first = service.attest_and_store(cycle_result=_cycle())
    second = service.attest_and_store(cycle_result=_cycle())

    assert first["attestationId"] == second["attestationId"] == 1
    assert first["attestationFingerprint"] == second["attestationFingerprint"]
    assert first["candidateId"] == 20
    assert first["candidateFingerprint"] == "c" * 64
    assert first["bundleFingerprints"] == ["a" * 64]
    assert first["advisoryStatus"] == "no_advice"
    assert first["productionEligible"] is False
    assert first["recommendationCandidateReady"] is False


def test_attestation_rejects_caller_supplied_bundle_trust():
    payload = _cycle()
    payload["policy"]["callerSuppliedFrozenBundleJsonTrusted"] = True
    service = RecommendationShadowLiveCycleAttestationService(repository=FakeRepository())

    with pytest.raises(ValueError, match="caller"):
        service.attest_and_store(cycle_result=payload)


def test_attestation_rejects_decision_uncertainty_identity_mismatch():
    payload = _cycle()
    payload["decisionResearch"]["uncertaintyFingerprint"] = "b" * 64
    service = RecommendationShadowLiveCycleAttestationService(repository=FakeRepository())

    with pytest.raises(ValueError, match="incertidumbre"):
        service.attest_and_store(cycle_result=payload)


def test_attestation_rejects_candidate_bundle_outside_revalidated_set():
    payload = _cycle()
    payload["candidate"]["horizons"]["30"]["bundleFingerprint"] = "b" * 64
    service = RecommendationShadowLiveCycleAttestationService(repository=FakeRepository())

    with pytest.raises(ValueError, match="no atestado"):
        service.attest_and_store(cycle_result=payload)


def test_attestation_detects_persisted_artifact_fingerprint_tampering():
    repository = FakeRepository()
    service = RecommendationShadowLiveCycleAttestationService(repository=repository)
    service.attest_and_store(cycle_result=_cycle())
    repository.rows[20]["attestation_fingerprint"] = "0" * 64

    with pytest.raises(ValueError, match="huella persistida"):
        service.get_for_candidate(candidate_id=20)


def test_attestation_rejects_non_persisted_cycle_status():
    payload = _cycle()
    payload["status"] = "shadow_live_cycle_blocked"
    service = RecommendationShadowLiveCycleAttestationService(repository=FakeRepository())

    with pytest.raises(ValueError, match="persistido"):
        service.attest_and_store(cycle_result=payload)

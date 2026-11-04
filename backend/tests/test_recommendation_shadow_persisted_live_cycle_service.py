from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_persisted_live_cycle_service import (
    RecommendationShadowPersistedLiveCycleService,
)


BUNDLE_FP = "a" * 64
CANDIDATE_FP = "c" * 64


class FakeFrozenRepository:
    def __init__(self, row=None):
        self.row = row or {
            "bundle_fingerprint": BUNDLE_FP,
            "bundle": {
                "bundleFingerprint": BUNDLE_FP,
                "horizonDays": 30,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
            },
        }
        self.calls = []

    def get_by_fingerprint(self, fingerprint):
        self.calls.append(fingerprint)
        return None if self.row is None else dict(self.row)


class FakeGatedFreezeService:
    def __init__(self):
        self.calls = []

    def validate_bundle(self, bundle):
        self.calls.append(bundle)
        return dict(bundle)


class FakeLiveCycleService:
    def __init__(self, payload=None):
        self.payload = payload or _successful_cycle()
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeAttestationService:
    def __init__(self, payload=None):
        self.payload = payload or {
            "status": "shadow_live_cycle_attestation_available",
            "attestationId": 50,
            "attestationFingerprint": "f" * 64,
            "candidateId": 20,
            "candidateFingerprint": CANDIDATE_FP,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
        }
        self.calls = []

    def attest_and_store(self, *, cycle_result):
        self.calls.append(cycle_result)
        return dict(self.payload)


def _successful_cycle():
    return {
        "status": "shadow_live_cycle_persisted",
        "snapshotId": 10,
        "candidateId": 20,
        "candidateFingerprint": CANDIDATE_FP,
        "confirmationEvidenceFingerprint": "d" * 64,
        "uncertaintyFingerprint": "e" * 64,
        "decisionResearchFingerprint": "1" * 64,
        "symbol": "TEST",
        "asOf": "2026-09-01T00:00:00+00:00",
        "benchmarkSymbol": "SPY",
        "candidate": {
            "candidateFingerprint": CANDIDATE_FP,
            "horizons": {
                "30": {
                    "horizonDays": 30,
                    "bundleFingerprint": BUNDLE_FP,
                }
            },
        },
        "decisionResearch": {
            "candidateFingerprint": CANDIDATE_FP,
            "uncertaintyFingerprint": "e" * 64,
            "decisionResearchFingerprint": "1" * 64,
        },
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _service(*, live=None, attestation=None, repository=None):
    frozen = repository or FakeFrozenRepository()
    gated = FakeGatedFreezeService()
    live_service = FakeLiveCycleService(live or _successful_cycle())
    attestation_service = FakeAttestationService(attestation)
    service = RecommendationShadowPersistedLiveCycleService(
        frozen_repository=frozen,
        gated_freeze_service=gated,
        live_cycle_service=live_service,
        attestation_service=attestation_service,
    )
    return service, frozen, gated, live_service, attestation_service


def test_successful_trusted_cycle_is_attested_after_revalidated_persisted_bundle_load():
    service, frozen, gated, live, attestation = _service()
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    result = service.run(
        symbol="TEST",
        as_of=as_of,
        bundle_fingerprints=[BUNDLE_FP],
        benchmark_symbol="SPY",
        horizons=[30],
    )

    assert frozen.calls == [BUNDLE_FP]
    assert gated.calls[0]["bundleFingerprint"] == BUNDLE_FP
    assert live.calls[0]["gated_bundles"][0]["bundleFingerprint"] == BUNDLE_FP
    assert len(attestation.calls) == 1
    attested_input = attestation.calls[0]
    assert attested_input["frozenCandidateSource"] == "sqlite_persisted_and_revalidated"
    assert attested_input["bundleFingerprints"] == [BUNDLE_FP]
    assert attested_input["policy"]["callerSuppliedFrozenBundleJsonTrusted"] is False
    assert attested_input["policy"]["frozenBundleIntegrity"] == "gated_freeze_revalidated_after_load"
    assert result["liveCycleAttestationId"] == 50
    assert result["liveCycleAttestationFingerprint"] == "f" * 64
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False


def test_blocked_cycle_is_not_falsely_attested():
    blocked = {
        "status": "shadow_live_cycle_blocked",
        "stage": "confirmed_inference",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "policy": {},
    }
    service, _, _, _, attestation = _service(live=blocked)

    result = service.run(
        symbol="TEST",
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        bundle_fingerprints=[BUNDLE_FP],
        benchmark_symbol="SPY",
        horizons=[30],
    )

    assert result["status"] == "shadow_live_cycle_blocked"
    assert attestation.calls == []
    assert "liveCycleAttestationId" not in result


def test_wrapper_fails_closed_if_attestation_changes_candidate_identity():
    bad_attestation = {
        "status": "shadow_live_cycle_attestation_available",
        "attestationId": 50,
        "attestationFingerprint": "f" * 64,
        "candidateId": 999,
        "candidateFingerprint": CANDIDATE_FP,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }
    service, _, _, _, _ = _service(attestation=bad_attestation)

    with pytest.raises(RuntimeError, match="candidateId"):
        service.run(
            symbol="TEST",
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bundle_fingerprints=[BUNDLE_FP],
            benchmark_symbol="SPY",
            horizons=[30],
        )


def test_wrapper_rejects_duplicate_horizon_even_when_bundle_fingerprints_differ():
    second_fp = "b" * 64

    class MultiFrozenRepository:
        def get_by_fingerprint(self, fingerprint):
            return {
                "bundle_fingerprint": fingerprint,
                "bundle": {
                    "bundleFingerprint": fingerprint,
                    "horizonDays": 30,
                    "advisoryStatus": "no_advice",
                    "productionEligible": False,
                },
            }

    service, _, _, live, attestation = _service(repository=MultiFrozenRepository())

    with pytest.raises(ValueError, match="mismo horizonte"):
        service.run(
            symbol="TEST",
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bundle_fingerprints=[BUNDLE_FP, second_fp],
            benchmark_symbol="SPY",
            horizons=[30],
        )
    assert live.calls == []
    assert attestation.calls == []

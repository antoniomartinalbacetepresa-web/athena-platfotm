from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.recommendation_shadow_live_candidate_store_service import (
    RecommendationShadowLiveCandidateStoreService,
)


class FakeCandidateService:
    def validate_artifact(self, candidate):
        if candidate.get("tampered"):
            raise ValueError("tampered")
        return candidate


class FakeSnapshotRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_snapshot(self, snapshot_id):
        return deepcopy(self.snapshot) if self.snapshot is not None else None


class FakeRepository:
    def __init__(self):
        self.saved = []
        self.rows = {}

    def save(self, **kwargs):
        self.saved.append(kwargs)
        candidate_id = 1
        self.rows[candidate_id] = {
            "id": candidate_id,
            "candidate_fingerprint": kwargs["candidate_fingerprint"],
            "artifact": deepcopy(kwargs["artifact"]),
        }
        return candidate_id

    def get(self, candidate_id):
        return deepcopy(self.rows.get(candidate_id))


def _snapshot():
    return {
        "id": 10,
        "instrument_id": 123,
        "symbol": "TEST",
        "data_cutoff_at": "2025-06-01T00:00:00+00:00",
    }


def _candidate():
    return {
        "status": "shadow_live_candidate_inferred",
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": "c" * 64,
        "confirmationEvidenceFingerprint": "d" * 64,
        "instrumentId": 123,
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
        "recommendationCandidateReady": False,
        "action": None,
        "score": None,
        "conviction": None,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _service(snapshot=None):
    repository = FakeRepository()
    return RecommendationShadowLiveCandidateStoreService(
        repository=repository,
        snapshot_repository=FakeSnapshotRepository(
            _snapshot() if snapshot is None else snapshot
        ),
        candidate_service=FakeCandidateService(),
    ), repository


def test_store_binds_validated_candidate_to_exact_pit_snapshot():
    service, repository = _service()
    candidate = _candidate()

    result = service.store(snapshot_id=10, candidate=candidate)

    assert result["status"] == "shadow_live_candidate_persisted"
    assert result["candidateId"] == 1
    assert result["snapshotId"] == 10
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert repository.saved[0]["artifact"] == candidate
    assert repository.saved[0]["snapshot_id"] == 10


def test_store_rejects_symbol_mismatch():
    snapshot = _snapshot()
    snapshot["symbol"] = "OTHER"
    service, _ = _service(snapshot)

    with pytest.raises(ValueError, match="símbolo"):
        service.store(snapshot_id=10, candidate=_candidate())


def test_store_rejects_instrument_mismatch():
    snapshot = _snapshot()
    snapshot["instrument_id"] = 999
    service, _ = _service(snapshot)

    with pytest.raises(ValueError, match="instrumento"):
        service.store(snapshot_id=10, candidate=_candidate())


def test_store_rejects_point_in_time_cutoff_mismatch():
    snapshot = _snapshot()
    snapshot["data_cutoff_at"] = "2025-05-31T00:00:00+00:00"
    service, _ = _service(snapshot)

    with pytest.raises(ValueError, match="mismo corte PIT"):
        service.store(snapshot_id=10, candidate=_candidate())


def test_store_rejects_non_advisory_shadow_contract_violation():
    service, _ = _service()
    candidate = _candidate()
    candidate["action"] = "buy"

    with pytest.raises(ValueError, match="acción"):
        service.store(snapshot_id=10, candidate=candidate)


def test_store_rejects_missing_snapshot():
    repository = FakeRepository()
    service = RecommendationShadowLiveCandidateStoreService(
        repository=repository,
        snapshot_repository=FakeSnapshotRepository(None),
        candidate_service=FakeCandidateService(),
    )

    with pytest.raises(ValueError, match="no existe"):
        service.store(snapshot_id=10, candidate=_candidate())

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.recommendation_shadow_live_uncertainty_store_service import (
    RecommendationShadowLiveUncertaintyStoreService,
)


class FakeCandidateRepository:
    def __init__(self, row=None):
        self.row = row or {
            "id": 20,
            "candidate_fingerprint": "c" * 64,
        }

    def get(self, candidate_id):
        if self.row is None or candidate_id != self.row.get("id"):
            return None
        return deepcopy(self.row)


class FakeUncertaintyRepository:
    def __init__(self):
        self.saved = []
        self.rows = {}

    def save(self, **kwargs):
        self.saved.append(deepcopy(kwargs))
        uncertainty_id = 30
        self.rows[uncertainty_id] = {
            "id": uncertainty_id,
            "candidate_id": kwargs["candidate_id"],
            "candidate_fingerprint": kwargs["candidate_fingerprint"],
            "uncertainty_fingerprint": "e" * 64,
            "artifact_version": kwargs["artifact_version"],
            "artifact": deepcopy(kwargs["artifact"]),
        }
        return uncertainty_id

    def get(self, uncertainty_id):
        row = self.rows.get(uncertainty_id)
        return deepcopy(row) if row is not None else None


def _uncertainty():
    return {
        "artifactVersion": "shadow-live-uncertainty-v1",
        "candidateId": 20,
        "candidateFingerprint": "c" * 64,
        "calibratedHorizonCount": 1,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "action": None,
        "conviction": None,
        "policy": {
            "cutoff": "candidate_as_of_not_request_time",
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def test_store_validates_candidate_identity_and_reloads_artifact():
    uncertainty_repository = FakeUncertaintyRepository()
    service = RecommendationShadowLiveUncertaintyStoreService(
        candidate_repository=FakeCandidateRepository(),
        uncertainty_repository=uncertainty_repository,
    )

    result = service.store(candidate_id=20, uncertainty=_uncertainty())

    assert result["status"] == "shadow_live_uncertainty_persisted"
    assert result["uncertaintyId"] == 30
    assert result["uncertaintyFingerprint"] == "e" * 64
    assert result["calibratedHorizonCount"] == 1
    assert result["productionEligible"] is False
    assert uncertainty_repository.saved[0]["artifact"] == _uncertainty()


def test_store_rejects_candidate_id_or_fingerprint_mismatch():
    service = RecommendationShadowLiveUncertaintyStoreService(
        candidate_repository=FakeCandidateRepository(),
        uncertainty_repository=FakeUncertaintyRepository(),
    )
    uncertainty = _uncertainty()
    uncertainty["candidateId"] = 21
    with pytest.raises(ValueError, match="candidate_id"):
        service.store(candidate_id=20, uncertainty=uncertainty)

    uncertainty = _uncertainty()
    uncertainty["candidateFingerprint"] = "d" * 64
    with pytest.raises(ValueError, match="cambió la identidad"):
        service.store(candidate_id=20, uncertainty=uncertainty)


def test_store_fails_closed_on_shadow_contract_violations():
    service = RecommendationShadowLiveUncertaintyStoreService(
        candidate_repository=FakeCandidateRepository(),
        uncertainty_repository=FakeUncertaintyRepository(),
    )
    for field, value in (
        ("advisoryStatus", "buy"),
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("action", "buy"),
        ("conviction", 0.9),
    ):
        uncertainty = _uncertainty()
        uncertainty[field] = value
        with pytest.raises(ValueError):
            service.store(candidate_id=20, uncertainty=uncertainty)


def test_store_rejects_policy_that_moves_cutoff_or_enables_automation():
    service = RecommendationShadowLiveUncertaintyStoreService(
        candidate_repository=FakeCandidateRepository(),
        uncertainty_repository=FakeUncertaintyRepository(),
    )
    for field, value in (
        ("cutoff", "request_time"),
        ("automaticModelMutation", True),
        ("automaticProductionPromotion", True),
        ("automaticTrading", True),
    ):
        uncertainty = _uncertainty()
        uncertainty["policy"][field] = value
        with pytest.raises(ValueError):
            service.store(candidate_id=20, uncertainty=uncertainty)

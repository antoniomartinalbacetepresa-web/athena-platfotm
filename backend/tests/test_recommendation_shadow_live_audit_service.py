from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.recommendation_shadow_live_audit_service import (
    RecommendationShadowLiveAuditService,
)


class FakeCandidateRepository:
    def __init__(self, row):
        self.row = row

    def get(self, candidate_id):
        if self.row is None or candidate_id != self.row.get("id"):
            return None
        return deepcopy(self.row)


class FakeUncertaintyRepository:
    def __init__(self, row):
        self.row = row

    def get_for_candidate(self, candidate_id):
        if self.row is None or candidate_id != self.row.get("candidate_id"):
            return None
        return deepcopy(self.row)


class FakeSnapshotRepository:
    def __init__(self, row):
        self.row = row

    def get_snapshot(self, snapshot_id):
        if self.row is None or snapshot_id != self.row.get("id"):
            return None
        return deepcopy(self.row)


class FakeCandidateService:
    def validate_artifact(self, artifact):
        return deepcopy(artifact)


def _candidate():
    return {
        "artifactVersion": "shadow-live-candidate-v1",
        "status": "shadow_live_candidate_inferred",
        "candidateFingerprint": "c" * 64,
        "confirmationEvidenceFingerprint": "d" * 64,
        "instrumentId": 7,
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
        "action": None,
        "score": None,
        "conviction": None,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _candidate_row():
    return {
        "id": 20,
        "snapshot_id": 10,
        "candidate_fingerprint": "c" * 64,
        "artifact": _candidate(),
    }


def _snapshot():
    return {
        "id": 10,
        "instrument_id": 7,
        "symbol": "TEST",
        "data_cutoff_at": "2025-06-01T00:00:00+00:00",
    }


def _uncertainty():
    return {
        "artifactVersion": "shadow-live-uncertainty-v1",
        "status": "shadow_live_empirical_uncertainty_available",
        "candidateId": 20,
        "candidateFingerprint": "c" * 64,
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
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


def _uncertainty_row():
    return {
        "id": 30,
        "candidate_id": 20,
        "candidate_fingerprint": "c" * 64,
        "uncertainty_fingerprint": "e" * 64,
        "artifact": _uncertainty(),
    }


def _service(*, candidate_row=None, uncertainty_row="default", snapshot=None):
    resolved_uncertainty = (
        _uncertainty_row() if uncertainty_row == "default" else uncertainty_row
    )
    return RecommendationShadowLiveAuditService(
        candidate_repository=FakeCandidateRepository(
            _candidate_row() if candidate_row is None else candidate_row
        ),
        uncertainty_repository=FakeUncertaintyRepository(resolved_uncertainty),
        snapshot_repository=FakeSnapshotRepository(_snapshot() if snapshot is None else snapshot),
        candidate_service=FakeCandidateService(),
    )


def test_audit_returns_candidate_and_exact_sealed_uncertainty_without_recomputation():
    result = _service().get(candidate_id=20)

    assert result["status"] == "shadow_live_audit_available"
    assert result["evidenceStatus"] == "candidate_and_uncertainty_immutably_available"
    assert result["candidate"] == _candidate()
    assert result["uncertainty"] == _uncertainty()
    assert result["uncertaintyFingerprint"] == "e" * 64
    assert result["policy"]["source"] == "persisted_immutable_artifacts_only"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["action"] is None


def test_legacy_candidate_without_uncertainty_is_reported_incomplete_never_recomputed():
    result = _service(uncertainty_row=None).get(candidate_id=20)

    assert result["evidenceStatus"] == "legacy_candidate_uncertainty_not_sealed"
    assert result["uncertainty"] is None
    assert result["uncertaintyId"] is None
    assert result["uncertaintyFingerprint"] is None
    assert result["policy"]["missingHistoricalUncertainty"] == "reported_missing_never_recomputed"


def test_unknown_candidate_is_rejected():
    service = RecommendationShadowLiveAuditService(
        candidate_repository=FakeCandidateRepository(None),
        uncertainty_repository=FakeUncertaintyRepository(None),
        snapshot_repository=FakeSnapshotRepository(None),
        candidate_service=FakeCandidateService(),
    )

    with pytest.raises(ValueError, match="no existe"):
        service.get(candidate_id=20)


def test_candidate_fingerprint_and_snapshot_identity_mismatches_fail_closed():
    row = _candidate_row()
    row["candidate_fingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="fingerprint persistido"):
        _service(candidate_row=row).get(candidate_id=20)

    snapshot = _snapshot()
    snapshot["instrument_id"] = 8
    with pytest.raises(ValueError, match="otro instrumento"):
        _service(snapshot=snapshot).get(candidate_id=20)


def test_uncertainty_candidate_identity_symbol_and_cutoff_mismatches_fail_closed():
    for field, value, message in (
        ("candidateFingerprint", "f" * 64, "otro fingerprint"),
        ("symbol", "OTHER", "otro símbolo"),
        ("asOf", "2025-06-02T00:00:00+00:00", "otro instante"),
    ):
        row = _uncertainty_row()
        row["artifact"][field] = value
        with pytest.raises(ValueError, match=message):
            _service(uncertainty_row=row).get(candidate_id=20)


def test_uncertainty_sidecar_fingerprint_mismatch_fails_closed():
    row = _uncertainty_row()
    row["candidate_fingerprint"] = "f" * 64

    with pytest.raises(ValueError, match="otro candidato"):
        _service(uncertainty_row=row).get(candidate_id=20)


def test_audit_rejects_any_advice_or_production_payload():
    candidate_row = _candidate_row()
    candidate_row["artifact"]["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible=False"):
        _service(candidate_row=candidate_row).get(candidate_id=20)

    uncertainty_row = _uncertainty_row()
    uncertainty_row["artifact"]["action"] = "buy"
    with pytest.raises(ValueError, match="acción"):
        _service(uncertainty_row=uncertainty_row).get(candidate_id=20)

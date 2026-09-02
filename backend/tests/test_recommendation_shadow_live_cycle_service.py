from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_cycle_service import (
    RecommendationShadowLiveCycleService,
)


class FakeCaptureService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def capture(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeCandidatePipeline:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeStoreService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def store(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeUncertaintyService:
    def __init__(self, payload=None):
        self.payload = payload or _uncertainty()
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeUncertaintyStoreService:
    def __init__(self, payload=None):
        self.payload = payload or _sealed_uncertainty()
        self.calls = []

    def store(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


def _capture():
    return {
        "status": "captured_for_calibration",
        "snapshotId": 10,
        "advisoryStatus": "no_advice",
    }


def _candidate():
    return {
        "status": "shadow_live_candidate_inferred",
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
        "inferredHorizonCount": 2,
        "candidateFingerprint": "c" * 64,
        "action": None,
        "score": None,
        "conviction": None,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _persisted():
    return {
        "status": "shadow_live_candidate_persisted",
        "candidateId": 20,
        "snapshotId": 10,
        "candidateFingerprint": "c" * 64,
        "confirmationEvidenceFingerprint": "d" * 64,
        "action": None,
        "score": None,
        "conviction": None,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _uncertainty():
    return {
        "artifactVersion": "shadow-live-uncertainty-v1",
        "status": "shadow_live_empirical_uncertainty_pending",
        "candidateId": 20,
        "candidateFingerprint": "c" * 64,
        "calibratedHorizonCount": 0,
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


def _sealed_uncertainty():
    return {
        "status": "shadow_live_uncertainty_persisted",
        "uncertaintyId": 30,
        "candidateId": 20,
        "candidateFingerprint": "c" * 64,
        "uncertaintyFingerprint": "e" * 64,
        "artifactVersion": "shadow-live-uncertainty-v1",
        "calibratedHorizonCount": 0,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "action": None,
        "conviction": None,
    }


def _service(
    *,
    capture=None,
    candidate=None,
    persisted=None,
    uncertainty=None,
    sealed_uncertainty=None,
):
    uncertainty_service = FakeUncertaintyService(uncertainty or _uncertainty())
    uncertainty_store = FakeUncertaintyStoreService(
        sealed_uncertainty or _sealed_uncertainty()
    )
    service = RecommendationShadowLiveCycleService(
        capture_service=FakeCaptureService(capture or _capture()),
        candidate_pipeline=FakeCandidatePipeline(candidate or _candidate()),
        store_service=FakeStoreService(persisted or _persisted()),
        uncertainty_service=uncertainty_service,
        uncertainty_store_service=uncertainty_store,
    )
    return service, uncertainty_service, uncertainty_store


def test_cycle_connects_capture_inference_persistence_uncertainty_and_seal():
    capture = FakeCaptureService(_capture())
    candidate = FakeCandidatePipeline(_candidate())
    store = FakeStoreService(_persisted())
    uncertainty = FakeUncertaintyService()
    uncertainty_store = FakeUncertaintyStoreService()
    service = RecommendationShadowLiveCycleService(
        capture_service=capture,
        candidate_pipeline=candidate,
        store_service=store,
        uncertainty_service=uncertainty,
        uncertainty_store_service=uncertainty_store,
    )
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    bundles = [{"bundleFingerprint": "bundle"}]

    result = service.run(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=bundles,
        benchmark_symbol="spy",
        horizons=[7, 30, 90],
    )

    assert result["status"] == "shadow_live_cycle_persisted"
    assert result["snapshotId"] == 10
    assert result["candidateId"] == 20
    assert result["uncertaintyId"] == 30
    assert result["uncertaintyFingerprint"] == "e" * 64
    assert result["benchmarkSymbol"] == "SPY"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["uncertainty"]["status"] == "shadow_live_empirical_uncertainty_pending"
    assert result["empiricalUncertaintyHorizonCount"] == 0
    assert capture.calls[0]["benchmark_symbol"] == "SPY"
    assert candidate.calls[0]["gated_bundles"] == bundles
    assert store.calls[0]["snapshot_id"] == 10
    assert store.calls[0]["candidate"] == _candidate()
    assert uncertainty.calls == [{"candidate_id": 20}]
    assert uncertainty_store.calls == [
        {"candidate_id": 20, "uncertainty": _uncertainty()}
    ]


def test_cycle_stops_after_pit_capture_block():
    capture = FakeCaptureService(
        {
            "status": "not_captured",
            "reason": "evidence blocked",
            "blockers": ["valuation_not_ready"],
            "snapshotId": None,
            "advisoryStatus": "no_advice",
        }
    )
    candidate = FakeCandidatePipeline(_candidate())
    store = FakeStoreService(_persisted())
    uncertainty = FakeUncertaintyService()
    uncertainty_store = FakeUncertaintyStoreService()
    service = RecommendationShadowLiveCycleService(
        capture_service=capture,
        candidate_pipeline=candidate,
        store_service=store,
        uncertainty_service=uncertainty,
        uncertainty_store_service=uncertainty_store,
    )

    result = service.run(
        symbol="TEST",
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
        gated_bundles=[],
        benchmark_symbol="SPY",
    )

    assert result["status"] == "shadow_live_cycle_blocked"
    assert result["stage"] == "pit_capture"
    assert result["blockers"] == ["valuation_not_ready"]
    assert candidate.calls == []
    assert store.calls == []
    assert uncertainty.calls == []
    assert uncertainty_store.calls == []


def test_cycle_keeps_snapshot_when_confirmed_inference_is_not_ready():
    blocked_candidate = _candidate()
    blocked_candidate["status"] = "shadow_live_candidate_blocked"
    blocked_candidate["reason"] = "post_selection_multi_horizon_confirmation_not_ready"
    candidate = FakeCandidatePipeline(blocked_candidate)
    store = FakeStoreService(_persisted())
    uncertainty = FakeUncertaintyService()
    uncertainty_store = FakeUncertaintyStoreService()
    service = RecommendationShadowLiveCycleService(
        capture_service=FakeCaptureService(_capture()),
        candidate_pipeline=candidate,
        store_service=store,
        uncertainty_service=uncertainty,
        uncertainty_store_service=uncertainty_store,
    )

    result = service.run(
        symbol="TEST",
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
        gated_bundles=[],
        benchmark_symbol="SPY",
    )

    assert result["status"] == "shadow_live_cycle_blocked"
    assert result["stage"] == "confirmed_inference"
    assert result["snapshotId"] == 10
    assert store.calls == []
    assert uncertainty.calls == []
    assert uncertainty_store.calls == []


def test_cycle_fails_closed_if_candidate_assigns_action():
    candidate = _candidate()
    candidate["action"] = "buy"
    service, uncertainty, uncertainty_store = _service(candidate=candidate)

    with pytest.raises(ValueError, match="action"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="SPY",
        )
    assert uncertainty.calls == []
    assert uncertainty_store.calls == []


def test_cycle_fails_closed_if_uncertainty_promotes_or_assigns_action():
    for field, value, message in (
        ("productionEligible", True, "habilitar producción"),
        ("recommendationCandidateReady", True, "habilitar recomendaciones"),
        ("actionThresholdCalibrationResearchEligible", True, "promover calibración"),
        ("action", "buy", "asignar action"),
        ("conviction", 0.9, "convicción"),
    ):
        uncertainty = _uncertainty()
        uncertainty[field] = value
        service, fake_uncertainty, uncertainty_store = _service(
            uncertainty=uncertainty
        )
        with pytest.raises(ValueError, match=message):
            service.run(
                symbol="TEST",
                as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
                gated_bundles=[],
                benchmark_symbol="SPY",
            )
        assert fake_uncertainty.calls == [{"candidate_id": 20}]
        assert uncertainty_store.calls == []


def test_cycle_fails_closed_if_uncertainty_changes_candidate_identity():
    uncertainty = _uncertainty()
    uncertainty["candidateFingerprint"] = "e" * 64
    service, _, uncertainty_store = _service(uncertainty=uncertainty)

    with pytest.raises(RuntimeError, match="cambió el candidato"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="SPY",
        )
    assert uncertainty_store.calls == []


def test_cycle_fails_closed_if_uncertainty_seal_changes_candidate_identity():
    sealed = _sealed_uncertainty()
    sealed["candidateFingerprint"] = "f" * 64
    service, _, uncertainty_store = _service(sealed_uncertainty=sealed)

    with pytest.raises(RuntimeError, match="sello de incertidumbre"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="SPY",
        )
    assert uncertainty_store.calls == [
        {"candidate_id": 20, "uncertainty": _uncertainty()}
    ]


def test_cycle_requires_explicit_benchmark_symbol():
    service, uncertainty, uncertainty_store = _service()

    with pytest.raises(ValueError, match="benchmark_symbol"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="",
        )
    assert uncertainty.calls == []
    assert uncertainty_store.calls == []

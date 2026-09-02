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


def test_cycle_connects_capture_inference_and_persistence():
    capture = FakeCaptureService(_capture())
    candidate = FakeCandidatePipeline(_candidate())
    store = FakeStoreService(_persisted())
    service = RecommendationShadowLiveCycleService(
        capture_service=capture,
        candidate_pipeline=candidate,
        store_service=store,
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
    assert result["benchmarkSymbol"] == "SPY"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert capture.calls[0]["benchmark_symbol"] == "SPY"
    assert candidate.calls[0]["gated_bundles"] == bundles
    assert store.calls[0]["snapshot_id"] == 10
    assert store.calls[0]["candidate"] == _candidate()


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
    service = RecommendationShadowLiveCycleService(
        capture_service=capture,
        candidate_pipeline=candidate,
        store_service=store,
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


def test_cycle_keeps_snapshot_when_confirmed_inference_is_not_ready():
    blocked_candidate = _candidate()
    blocked_candidate["status"] = "shadow_live_candidate_blocked"
    blocked_candidate["reason"] = "post_selection_multi_horizon_confirmation_not_ready"
    candidate = FakeCandidatePipeline(blocked_candidate)
    store = FakeStoreService(_persisted())
    service = RecommendationShadowLiveCycleService(
        capture_service=FakeCaptureService(_capture()),
        candidate_pipeline=candidate,
        store_service=store,
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


def test_cycle_fails_closed_if_candidate_assigns_action():
    candidate = _candidate()
    candidate["action"] = "buy"
    service = RecommendationShadowLiveCycleService(
        capture_service=FakeCaptureService(_capture()),
        candidate_pipeline=FakeCandidatePipeline(candidate),
        store_service=FakeStoreService(_persisted()),
    )

    with pytest.raises(ValueError, match="action"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="SPY",
        )


def test_cycle_requires_explicit_benchmark_symbol():
    service = RecommendationShadowLiveCycleService(
        capture_service=FakeCaptureService(_capture()),
        candidate_pipeline=FakeCandidatePipeline(_candidate()),
        store_service=FakeStoreService(_persisted()),
    )

    with pytest.raises(ValueError, match="benchmark_symbol"):
        service.run(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
            benchmark_symbol="",
        )

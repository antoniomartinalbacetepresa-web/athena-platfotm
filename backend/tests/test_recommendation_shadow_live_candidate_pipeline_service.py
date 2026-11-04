from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_candidate_pipeline_service import (
    RecommendationShadowLiveCandidatePipelineService,
)


class FakeConfirmationService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class FakeCandidateService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


def _confirmation():
    return {
        "status": "shadow_post_selection_multi_horizon_confirmed",
        "confirmationEvidenceFingerprint": "confirmation-a",
        "postSelectionProtocolEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _candidate():
    return {
        "status": "shadow_live_candidate_inferred",
        "recommendationCandidateReady": False,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {"automaticTrading": False},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_pipeline_derives_confirmation_internally_and_passes_exact_artifact():
    confirmation_service = FakeConfirmationService(_confirmation())
    candidate_service = FakeCandidateService(_candidate())
    service = RecommendationShadowLiveCandidatePipelineService(
        confirmation_service=confirmation_service,
        candidate_service=candidate_service,
    )
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    bundles = [{"bundleFingerprint": "bundle-a"}]

    result = service.build(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=bundles,
        horizons=[7, 30, 90],
    )

    assert confirmation_service.calls == [
        {"gated_bundles": bundles, "as_of": as_of, "horizons": [7, 30, 90]}
    ]
    assert candidate_service.calls[0]["confirmation_artifact"] == _confirmation()
    assert result["confirmationDerivedInPipeline"] is True
    assert result["confirmationEvidenceFingerprint"] == "confirmation-a"
    assert result["policy"]["callerSuppliedConfirmationTrusted"] is False
    assert result["productionEligible"] is False


def test_pipeline_fails_closed_if_confirmation_attempts_production():
    confirmation = _confirmation()
    confirmation["productionEligible"] = True
    service = RecommendationShadowLiveCandidatePipelineService(
        confirmation_service=FakeConfirmationService(confirmation),
        candidate_service=FakeCandidateService(_candidate()),
    )

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.build(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
        )


def test_pipeline_fails_closed_if_candidate_assigns_action():
    candidate = _candidate()
    candidate["action"] = "buy"
    service = RecommendationShadowLiveCandidatePipelineService(
        confirmation_service=FakeConfirmationService(_confirmation()),
        candidate_service=FakeCandidateService(candidate),
    )

    with pytest.raises(ValueError, match="asignar una acción"):
        service.build(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
        )


def test_pipeline_fails_closed_if_candidate_publishes_uncalibrated_score():
    candidate = _candidate()
    candidate["score"] = 0.8
    service = RecommendationShadowLiveCandidatePipelineService(
        confirmation_service=FakeConfirmationService(_confirmation()),
        candidate_service=FakeCandidateService(candidate),
    )

    with pytest.raises(ValueError, match="score o convicción"):
        service.build(
            symbol="TEST",
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
            gated_bundles=[],
        )

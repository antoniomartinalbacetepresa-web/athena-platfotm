from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)


class FakeHoldoutService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def freeze(self, **kwargs):
        self.calls.append(kwargs)
        cutoff = kwargs["research_cutoff"]
        return {
            "status": "shadow_model_frozen",
            "researchCutoff": cutoff.isoformat(),
            "horizonDays": kwargs["horizon_days"],
            "ridgeLambda": kwargs["ridge_lambda"],
            "fingerprint": "model-fingerprint",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }


def _gate(*, eligible: bool = True, passing_30: bool = True):
    return {
        "status": (
            "shadow_candidate_may_enter_action_calibration_research"
            if eligible
            else "shadow_candidate_fails_research_gate"
        ),
        "evaluatedHorizonCount": 3,
        "passingHorizonCount": 2 if eligible else 1,
        "horizonPassRatio": 2.0 / 3.0 if eligible else 1.0 / 3.0,
        "researchStageEligible": eligible,
        "globalReasons": [] if eligible else ["insufficient_passing_horizons"],
        "horizons": {
            "7": {
                "horizonDays": 7,
                "evaluated": True,
                "passesResearchGate": True,
                "reasons": [],
            },
            "30": {
                "horizonDays": 30,
                "evaluated": True,
                "passesResearchGate": passing_30,
                "reasons": [] if passing_30 else ["baseline_win_rate_below_research_threshold"],
            },
            "90": {
                "horizonDays": 90,
                "evaluated": True,
                "passesResearchGate": eligible,
                "reasons": [],
            },
        },
        "thresholds": {
            "minimumEvaluatedHorizons": 3,
            "minimumPassingHorizons": 2,
        },
        "thresholdStatus": "provisional_research_only",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_freeze_requires_global_research_gate_pass():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)

    with pytest.raises(ValueError, match="no autoriza"):
        service.freeze(
            research_gate=_gate(eligible=False),
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
            ridge_lambda=1.0,
        )

    assert holdout.calls == []


def test_freeze_requires_requested_horizon_to_pass_gate():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)

    with pytest.raises(ValueError, match="no superó"):
        service.freeze(
            research_gate=_gate(passing_30=False),
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
            ridge_lambda=1.0,
        )

    assert holdout.calls == []


def test_gated_freeze_binds_gate_model_and_protocol_with_fingerprints():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)
    cutoff = datetime(2025, 7, 1, tzinfo=timezone.utc)

    first = service.freeze(
        research_gate=_gate(),
        research_cutoff=cutoff,
        horizon_days=30,
        ridge_lambda=1.0,
    )
    second = service.freeze(
        research_gate=_gate(),
        research_cutoff=cutoff,
        horizon_days=30,
        ridge_lambda=1.0,
    )

    assert first["status"] == "shadow_research_gated_model_frozen"
    assert first["researchGateFingerprint"] == second["researchGateFingerprint"]
    assert first["bundleFingerprint"] == second["bundleFingerprint"]
    assert first["modelFingerprint"] == "model-fingerprint"
    assert first["researchIdentity"] == "candidate_protocol_not_single_walk_forward_fold_model"
    assert first["productionEligible"] is False
    assert first["advisoryStatus"] == "no_advice"
    service.validate_bundle(first)


def test_bundle_validation_detects_research_gate_tampering():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    bundle = service.freeze(
        research_gate=_gate(),
        research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizon_days=30,
        ridge_lambda=1.0,
    )
    bundle["researchGateEvidence"]["passingHorizonCount"] = 99

    with pytest.raises(ValueError, match="research gate fue modificada"):
        service.validate_bundle(bundle)


def test_bundle_validation_detects_bundle_tampering():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    bundle = service.freeze(
        research_gate=_gate(),
        research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizon_days=30,
        ridge_lambda=1.0,
    )
    bundle["ridgeLambda"] = 10.0

    with pytest.raises(ValueError, match="bundle gated freeze fue modificado"):
        service.validate_bundle(bundle)


def test_freeze_rejects_naive_research_cutoff():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())

    with pytest.raises(ValueError, match="zona horaria"):
        service.freeze(
            research_gate=_gate(),
            research_cutoff=datetime(2025, 7, 1),
            horizon_days=30,
            ridge_lambda=1.0,
        )

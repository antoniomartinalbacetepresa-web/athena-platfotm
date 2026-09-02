from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_protocol_selection_service import (
    RecommendationShadowProtocolSelectionService,
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


def _gate(*, eligible: bool = True, passing_30: bool = True, source_fingerprint=None):
    if source_fingerprint is None:
        source_fingerprint = _selection()["sourceWalkForwardFingerprint"]
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
                "sourceWalkForwardFingerprint": "unused-7",
                "reasons": [],
            },
            "30": {
                "horizonDays": 30,
                "evaluated": True,
                "passesResearchGate": passing_30,
                "sourceWalkForwardFingerprint": source_fingerprint,
                "reasons": [] if passing_30 else ["baseline_win_rate_below_research_threshold"],
            },
            "90": {
                "horizonDays": 90,
                "evaluated": True,
                "passesResearchGate": eligible,
                "sourceWalkForwardFingerprint": "unused-90",
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


def _walk_forward(lambdas=(1.0, 1.0, 10.0)):
    candidates = [
        {"ridgeLambda": 0.1, "validation": {"mse": 0.3}},
        {"ridgeLambda": 1.0, "validation": {"mse": 0.2}},
        {"ridgeLambda": 10.0, "validation": {"mse": 0.4}},
    ]
    return {
        "status": "shadow_walk_forward_evaluated",
        "horizonDays": 30,
        "foldCount": len(lambdas),
        "evaluatedFoldCount": len(lambdas),
        "blockedFoldCount": 0,
        "folds": [
            {
                "foldIndex": index,
                "evaluation": {
                    "status": "shadow_linear_candidate_evaluated",
                    "horizonDays": 30,
                    "selection": {
                        "criterion": "minimum_validation_mse",
                        "ridgeLambda": ridge_lambda,
                        "candidates": candidates,
                    },
                    "advisoryStatus": "no_advice",
                    "productionEligible": False,
                },
            }
            for index, ridge_lambda in enumerate(lambdas)
        ],
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _selection(lambdas=(1.0, 1.0, 10.0)):
    return RecommendationShadowProtocolSelectionService().select(
        walk_forward_evidence=_walk_forward(lambdas),
        horizon_days=30,
    )


def test_freeze_requires_global_research_gate_pass():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)

    with pytest.raises(ValueError, match="no autoriza"):
        service.freeze(
            research_gate=_gate(eligible=False),
            protocol_selection=_selection(),
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
        )

    assert holdout.calls == []


def test_freeze_requires_requested_horizon_to_pass_gate():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)

    with pytest.raises(ValueError, match="no superó"):
        service.freeze(
            research_gate=_gate(passing_30=False),
            protocol_selection=_selection(),
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
        )

    assert holdout.calls == []


def test_gated_freeze_uses_only_research_derived_lambda_and_binds_fingerprints():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)
    cutoff = datetime(2025, 7, 1, tzinfo=timezone.utc)
    selection = _selection()

    first = service.freeze(
        research_gate=_gate(source_fingerprint=selection["sourceWalkForwardFingerprint"]),
        protocol_selection=selection,
        research_cutoff=cutoff,
        horizon_days=30,
    )
    second = service.freeze(
        research_gate=_gate(source_fingerprint=selection["sourceWalkForwardFingerprint"]),
        protocol_selection=selection,
        research_cutoff=cutoff,
        horizon_days=30,
    )

    assert first["status"] == "shadow_research_gated_model_frozen"
    assert first["bundleVersion"] == "shadow-gated-freeze-v2"
    assert first["ridgeLambda"] == selection["selectedRidgeLambda"] == 1.0
    assert holdout.calls[0]["ridge_lambda"] == 1.0
    assert first["sourceWalkForwardFingerprint"] == selection["sourceWalkForwardFingerprint"]
    assert first["researchGateFingerprint"] == second["researchGateFingerprint"]
    assert first["protocolSelectionFingerprint"] == second["protocolSelectionFingerprint"]
    assert first["bundleFingerprint"] == second["bundleFingerprint"]
    assert first["modelFingerprint"] == "model-fingerprint"
    assert first["researchIdentity"] == "candidate_protocol_not_single_walk_forward_fold_model"
    assert first["policy"]["manualPostResearchLambdaSelection"] is False
    assert first["policy"]["foldTestMetricsMaySelectLambda"] is False
    assert first["productionEligible"] is False
    assert first["advisoryStatus"] == "no_advice"
    service.validate_bundle(first)


def test_freeze_rejects_protocol_selection_from_different_walk_forward():
    holdout = FakeHoldoutService()
    service = RecommendationShadowGatedFreezeService(holdout_service=holdout)
    selection = _selection()

    with pytest.raises(ValueError, match="no procede"):
        service.freeze(
            research_gate=_gate(source_fingerprint="different-walk-forward"),
            protocol_selection=selection,
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
        )

    assert holdout.calls == []


def test_freeze_rejects_protocol_selection_for_another_horizon():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    selection = _selection()
    selection["horizonDays"] = 90

    with pytest.raises(ValueError):
        service.freeze(
            research_gate=_gate(),
            protocol_selection=selection,
            research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
            horizon_days=30,
        )


def test_bundle_validation_detects_research_gate_tampering():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    bundle = service.freeze(
        research_gate=_gate(),
        protocol_selection=_selection(),
        research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizon_days=30,
    )
    bundle["researchGateEvidence"]["passingHorizonCount"] = 99

    with pytest.raises(ValueError, match="research gate fue modificada"):
        service.validate_bundle(bundle)


def test_bundle_validation_detects_protocol_selection_tampering():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    bundle = service.freeze(
        research_gate=_gate(),
        protocol_selection=_selection(),
        research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizon_days=30,
    )
    bundle["protocolSelectionEvidence"]["selectedRidgeLambda"] = 10.0

    with pytest.raises(ValueError):
        service.validate_bundle(bundle)


def test_bundle_validation_detects_bundle_tampering():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())
    bundle = service.freeze(
        research_gate=_gate(),
        protocol_selection=_selection(),
        research_cutoff=datetime(2025, 7, 1, tzinfo=timezone.utc),
        horizon_days=30,
    )
    bundle["ridgeLambda"] = 10.0

    with pytest.raises(ValueError, match="bundle gated freeze fue modificado"):
        service.validate_bundle(bundle)


def test_freeze_rejects_naive_research_cutoff():
    service = RecommendationShadowGatedFreezeService(holdout_service=FakeHoldoutService())

    with pytest.raises(ValueError, match="zona horaria"):
        service.freeze(
            research_gate=_gate(),
            protocol_selection=_selection(),
            research_cutoff=datetime(2025, 7, 1),
            horizon_days=30,
        )

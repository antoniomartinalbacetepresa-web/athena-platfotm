from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class GateResult:
    def __init__(self, payload):
        self.payload = payload

    def to_api_dict(self):
        return deepcopy(self.payload)


class FakeEvidenceGateService:
    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, *, symbol, as_of):
        return GateResult(self.payload)


class FakeConfirmationService:
    def validate_artifact(self, artifact):
        if artifact.get("tampered"):
            raise ValueError("tampered")
        return artifact


class FakeGatedFreezeService:
    def validate_bundle(self, bundle):
        if bundle.get("tampered"):
            raise ValueError("tampered")
        return bundle


def _gate_payload(as_of: datetime):
    return {
        "status": "evidence_ready_for_calibration",
        "symbol": "TEST",
        "asOf": as_of.isoformat(),
        "instrumentId": 123,
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "market": {
            "status": "diagnostic_ready",
            "technicalScore": 0.4,
            "riskScore": 0.3,
            "return20d": 0.1,
            "return60d": None,
            "annualizedVolatility": 0.2,
            "maxDrawdown60d": -0.15,
        },
        "fundamentals": {
            "status": "diagnostic_ready",
            "coverageRatio": 0.9,
            "ratios": {
                "revenueGrowth": 0.08,
                "netMargin": 0.12,
                "liabilitiesToAssets": 0.45,
            },
        },
        "valuation": {
            "status": "diagnostic_ready",
            "reportedAnnualPe": 18.0,
        },
    }


def _model(horizon: int):
    return {
        "status": "shadow_model_frozen",
        "artifactVersion": "shadow-frozen-linear-v1",
        "featureSchemaVersion": "shadow-evidence-v1",
        "researchCutoff": "2025-01-01T00:00:00+00:00",
        "horizonDays": horizon,
        "ridgeLambda": 1.0,
        "features": ["technicalScore", "return60d", "reportedAnnualPe"],
        "medians": {"technicalScore": 0.0, "return60d": 0.05, "reportedAnnualPe": 15.0},
        "means": [0.0, 0.0, 15.0],
        "scales": [1.0, 0.1, 5.0],
        "intercept": 0.01,
        "coefficients": [0.02, 0.03, -0.01],
        "researchRowCount": 100,
        "fingerprint": f"model-{horizon}",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _bundle(horizon: int):
    return {
        "status": "shadow_research_gated_model_frozen",
        "researchGateFingerprint": "gate-a",
        "researchCutoff": "2025-01-01T00:00:00+00:00",
        "horizonDays": horizon,
        "bundleFingerprint": f"bundle-{horizon}",
        "frozenModel": _model(horizon),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _confirmation(as_of: datetime, *, ready: bool = True):
    return {
        "status": (
            "shadow_post_selection_multi_horizon_confirmed"
            if ready
            else "shadow_post_selection_multi_horizon_not_confirmed"
        ),
        "artifactVersion": "shadow-post-selection-multi-horizon-v1",
        "researchGateFingerprint": "gate-a",
        "researchCutoff": "2025-01-01T00:00:00+00:00",
        "asOf": as_of.isoformat(),
        "requestedHorizons": [7, 30, 90],
        "postSelectionProtocolEvidenceReady": ready,
        "confirmationEvidenceFingerprint": "confirmation-a",
        "horizons": {
            "7": {
                "horizonDays": 7,
                "passesConfirmationProtocol": True,
                "modelFingerprint": "model-7",
            },
            "30": {
                "horizonDays": 30,
                "passesConfirmationProtocol": False,
                "modelFingerprint": "model-30",
            },
            "90": {
                "horizonDays": 90,
                "passesConfirmationProtocol": True,
                "modelFingerprint": "model-90",
            },
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _service(as_of: datetime, gate_payload=None):
    return RecommendationShadowLiveCandidateService(
        evidence_gate_service=FakeEvidenceGateService(gate_payload or _gate_payload(as_of)),
        gated_freeze_service=FakeGatedFreezeService(),
        confirmation_service=FakeConfirmationService(),
    )


def test_live_candidate_infers_only_individually_confirmed_horizons():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    service = _service(as_of)

    result = service.build(
        symbol="test",
        as_of=as_of,
        gated_bundles=[_bundle(7), _bundle(30), _bundle(90)],
        confirmation_artifact=_confirmation(as_of),
    )

    assert result["status"] == "shadow_live_candidate_inferred"
    assert result["inferredHorizonCount"] == 2
    assert result["horizons"]["7"]["expectedExcessReturn"] is not None
    assert result["horizons"]["30"]["expectedExcessReturn"] is None
    assert result["horizons"]["90"]["expectedExcessReturn"] is not None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert service.validate_artifact(result) == result


def test_live_candidate_discloses_training_median_imputation_and_contributions():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    result = _service(as_of).build(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=[_bundle(7), _bundle(30), _bundle(90)],
        confirmation_artifact=_confirmation(as_of),
    )

    explanation = result["horizons"]["7"]["explanation"]
    assert explanation["imputedFeatures"] == ["return60d"]
    assert explanation["imputedFeatureCount"] == 1
    assert {item["feature"] for item in explanation["contributions"]} == {
        "technicalScore",
        "return60d",
        "reportedAnnualPe",
    }
    assert result["horizons"]["7"]["uncertaintyStatus"] == "not_calibrated_for_live_decision"
    assert result["horizons"]["7"]["scenarioStatus"] == "not_calibrated"


def test_live_candidate_blocks_when_multi_horizon_confirmation_is_not_ready():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    result = _service(as_of).build(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=[_bundle(7)],
        confirmation_artifact=_confirmation(as_of, ready=False),
    )

    assert result["status"] == "shadow_live_candidate_blocked"
    assert result["reason"] == "post_selection_multi_horizon_confirmation_not_ready"
    assert result["productionEligible"] is False


def test_live_candidate_blocks_when_current_pit_evidence_is_not_ready():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    gate = _gate_payload(as_of)
    gate["status"] = "evidence_blocked"
    gate["blockers"] = ["valuation_not_ready"]

    result = _service(as_of, gate).build(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=[_bundle(7), _bundle(90)],
        confirmation_artifact=_confirmation(as_of),
    )

    assert result["status"] == "shadow_live_candidate_blocked"
    assert result["reason"] == "current_point_in_time_evidence_not_ready"
    assert result["blockers"] == ["valuation_not_ready"]


def test_live_candidate_rejects_model_not_bound_to_confirmed_horizon():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    wrong = _bundle(7)
    wrong["frozenModel"]["fingerprint"] = "different-model"

    with pytest.raises(ValueError, match="modelo live no coincide"):
        _service(as_of).build(
            symbol="TEST",
            as_of=as_of,
            gated_bundles=[wrong, _bundle(90)],
            confirmation_artifact=_confirmation(as_of),
        )


def test_live_candidate_rejects_confirmation_from_future():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    future = datetime(2025, 6, 2, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="futuro"):
        _service(as_of).build(
            symbol="TEST",
            as_of=as_of,
            gated_bundles=[_bundle(7), _bundle(90)],
            confirmation_artifact=_confirmation(future),
        )


def test_live_candidate_artifact_detects_tampering():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    service = _service(as_of)
    result = service.build(
        symbol="TEST",
        as_of=as_of,
        gated_bundles=[_bundle(7), _bundle(30), _bundle(90)],
        confirmation_artifact=_confirmation(as_of),
    )
    tampered = deepcopy(result)
    tampered["horizons"]["7"]["expectedExcessReturn"] = 9.9

    with pytest.raises(ValueError, match="fue modificado"):
        service.validate_artifact(tampered)


def test_live_candidate_rejects_evidence_gate_attempting_production():
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    gate = _gate_payload(as_of)
    gate["productionEligible"] = True

    with pytest.raises(RuntimeError, match="productivo"):
        _service(as_of, gate).build(
            symbol="TEST",
            as_of=as_of,
            gated_bundles=[_bundle(7), _bundle(90)],
            confirmation_artifact=_confirmation(as_of),
        )

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_post_selection_multi_horizon_service import (
    RecommendationShadowPostSelectionMultiHorizonService,
)


class FakeGatedFreezeService:
    def validate_bundle(self, bundle):
        if bundle.get("productionEligible") is not False:
            raise ValueError("not shadow")
        return bundle


class FakePostSelectionPipeline:
    def __init__(self, results):
        self.results = results

    def evaluate_registered_selection(self, *, model_fingerprint, as_of):
        return deepcopy(self.results[model_fingerprint])


def _bundle(horizon: int, *, gate: str = "gate-a", cutoff: str = "2025-01-01T00:00:00+00:00"):
    fingerprint = f"model-{horizon}"
    return {
        "status": "shadow_research_gated_model_frozen",
        "researchGateFingerprint": gate,
        "researchCutoff": cutoff,
        "horizonDays": horizon,
        "bundleFingerprint": f"bundle-{horizon}",
        "frozenModel": {
            "fingerprint": fingerprint,
            "horizonDays": horizon,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _confirmed(horizon: int, *, improvement: float = 0.20, sign_accuracy: float = 0.60):
    return {
        "status": "shadow_post_selection_confirmation_evaluated",
        "modelFingerprint": f"model-{horizon}",
        "horizonDays": horizon,
        "confirmationStart": "2025-02-01T00:00:00+00:00",
        "confirmationRowCount": 25,
        "postSelectionConfirmationEvidenceReady": True,
        "metrics": {"mse": 0.8, "mae": 0.7, "signAccuracy": sign_accuracy},
        "zeroExcessReturnBaseline": {"mse": 1.0, "mae": 0.8, "signAccuracy": 0.5},
        "relativeMseImprovement": improvement,
        "beatsZeroBaselineOnMse": improvement > 0,
        "selectionFingerprint": f"selection-{horizon}",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _service(results, **kwargs):
    return RecommendationShadowPostSelectionMultiHorizonService(
        gated_freeze_service=FakeGatedFreezeService(),
        post_selection_pipeline=FakePostSelectionPipeline(results),
        **kwargs,
    )


def test_multi_horizon_confirmation_requires_coherent_research_lineage():
    service = _service({})
    bundles = [_bundle(7, gate="gate-a"), _bundle(30, gate="gate-b")]

    with pytest.raises(ValueError, match="misma research gate"):
        service.evaluate(
            gated_bundles=bundles,
            horizons=[7, 30],
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )


def test_three_confirmed_horizons_can_pass_research_confirmation_protocol():
    horizons = [7, 30, 90]
    results = {f"model-{horizon}": _confirmed(horizon) for horizon in horizons}
    service = _service(results)

    payload = service.evaluate(
        gated_bundles=[_bundle(horizon) for horizon in horizons],
        horizons=horizons,
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    assert payload["status"] == "shadow_post_selection_multi_horizon_confirmed"
    assert payload["confirmedHorizonCount"] == 3
    assert payload["passingHorizonCount"] == 3
    assert payload["postSelectionProtocolEvidenceReady"] is True
    assert payload["productionEligible"] is False
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["policy"]["confirmationDataCanFitActionThresholds"] is False
    assert len(payload["confirmationEvidenceFingerprint"]) == 64
    assert service.validate_artifact(payload) == payload


def test_weak_confirmed_horizon_counts_as_failure_not_missing_evidence():
    horizons = [7, 30, 90]
    results = {
        "model-7": _confirmed(7),
        "model-30": _confirmed(30, improvement=-0.05),
        "model-90": _confirmed(90),
    }
    service = _service(results)

    payload = service.evaluate(
        gated_bundles=[_bundle(horizon) for horizon in horizons],
        horizons=horizons,
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    assert payload["confirmedHorizonCount"] == 3
    assert payload["passingHorizonCount"] == 2
    assert payload["postSelectionProtocolEvidenceReady"] is False
    assert payload["horizons"]["30"]["confirmed"] is True
    assert payload["horizons"]["30"]["passesConfirmationProtocol"] is False


def test_missing_or_unregistered_horizon_cannot_inflate_pass_ratio():
    results = {
        "model-7": _confirmed(7),
        "model-30": {
            "status": "shadow_post_selection_not_registered",
            "modelFingerprint": "model-30",
            "postSelectionConfirmationEvidenceReady": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        },
    }
    service = _service(results, minimum_confirmed_horizons=2)

    payload = service.evaluate(
        gated_bundles=[_bundle(7), _bundle(30)],
        horizons=[7, 30, 90],
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )

    assert payload["confirmedHorizonCount"] == 1
    assert payload["postSelectionProtocolEvidenceReady"] is False
    assert payload["horizons"]["30"]["confirmed"] is False
    assert payload["horizons"]["90"]["status"] == "candidate_missing"


def test_tampered_confirmation_artifact_is_rejected():
    horizons = [7, 30, 90]
    service = _service(
        {f"model-{horizon}": _confirmed(horizon) for horizon in horizons}
    )
    payload = service.evaluate(
        gated_bundles=[_bundle(horizon) for horizon in horizons],
        horizons=horizons,
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    tampered = deepcopy(payload)
    tampered["horizons"]["7"]["relativeMseImprovement"] = 0.99

    with pytest.raises(ValueError, match="fue modificada"):
        service.validate_artifact(tampered)


def test_non_shadow_confirmation_fails_closed():
    result = _confirmed(7)
    result["productionEligible"] = True
    service = _service({"model-7": result}, minimum_confirmed_horizons=1)

    with pytest.raises(ValueError, match="productionEligible=False"):
        service.evaluate(
            gated_bundles=[_bundle(7)],
            horizons=[7],
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )


def test_duplicate_horizons_are_rejected():
    service = _service({})

    with pytest.raises(ValueError, match="no pueden repetirse"):
        service.evaluate(
            gated_bundles=[],
            horizons=[30, 30],
            as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

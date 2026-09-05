from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_production_promotion_evidence_service import (
    RecommendationProductionPromotionEvidenceService,
)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _confirmation() -> dict:
    core = {
        "artifactVersion": "shadow-post-selection-multi-horizon-v1",
        "researchGateFingerprint": "gate-abc",
        "researchCutoff": "2026-01-31T00:00:00+00:00",
        "asOf": "2026-08-31T00:00:00+00:00",
        "requestedHorizons": [7, 30],
        "confirmedHorizonCount": 2,
        "passingHorizonCount": 2,
        "confirmationPassRatio": 1.0,
        "postSelectionProtocolEvidenceReady": True,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "confirmed": True,
                "modelFingerprint": "model-7",
                "selectionFingerprint": "selection-7",
                "confirmationStart": "2026-02-01T00:00:00+00:00",
                "confirmationRowCount": 30,
                "metrics": {"signAccuracy": 0.60, "mse": 0.02},
                "relativeMseImprovement": 0.10,
                "beatsZeroBaselineOnMse": True,
            },
            "30": {
                "horizonDays": 30,
                "confirmed": True,
                "modelFingerprint": "model-30",
                "selectionFingerprint": "selection-30",
                "confirmationStart": "2026-02-01T00:00:00+00:00",
                "confirmationRowCount": 25,
                "metrics": {"signAccuracy": 0.58, "mse": 0.03},
                "relativeMseImprovement": 0.08,
                "beatsZeroBaselineOnMse": True,
            },
        },
        "thresholds": {"researchOnly": True},
    }
    return {
        **core,
        "confirmationEvidenceFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _protocol(service: RecommendationProductionPromotionEvidenceService) -> dict:
    core = {
        "artifactVersion": service.PROTOCOL_VERSION,
        "protocolId": "promotion-protocol-001",
        "registeredAt": "2026-01-15T00:00:00+00:00",
        "researchGateFingerprint": "gate-abc",
        "requiredHorizons": [7, 30],
        "criteriaByHorizon": {
            "7": {
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
            "30": {
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
        },
    }
    return {**core, "protocolFingerprint": service.fingerprint_protocol(core)}


def test_precommitted_protocol_can_mark_evidence_ready_without_enabling_production() -> None:
    service = RecommendationProductionPromotionEvidenceService()

    result = service.evaluate(
        confirmation_artifact=_confirmation(),
        promotion_protocol=_protocol(service),
    )

    assert result["status"] == "production_promotion_evidence_ready"
    assert result["productionPromotionEvidenceReady"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["automaticProductionPromotion"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["criteriaSource"] == (
        "explicit_precommitted_protocol_no_code_defaults"
    )


def test_protocol_registered_after_research_cutoff_fails_closed() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    core["registeredAt"] = "2026-02-01T00:00:00+00:00"
    protocol = {**core, "protocolFingerprint": service.fingerprint_protocol(core)}

    with pytest.raises(ValueError, match="researchCutoff"):
        service.evaluate(
            confirmation_artifact=_confirmation(),
            promotion_protocol=protocol,
        )


def test_tampered_confirmation_fingerprint_fails_closed() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["metrics"]["signAccuracy"] = 0.99

    with pytest.raises(ValueError, match="modificada"):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )


def test_non_finite_confirmation_metric_fails_closed_even_if_resigned() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["metrics"]["signAccuracy"] = float("nan")
    core_keys = (
        "artifactVersion",
        "researchGateFingerprint",
        "researchCutoff",
        "asOf",
        "requestedHorizons",
        "confirmedHorizonCount",
        "passingHorizonCount",
        "confirmationPassRatio",
        "postSelectionProtocolEvidenceReady",
        "horizons",
        "thresholds",
    )
    core = {key: confirmation.get(key) for key in core_keys}
    confirmation["confirmationEvidenceFingerprint"] = "re-signed"

    # The service must reject NaN before any comparison can treat it as evidence.
    with pytest.raises(ValueError):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )


def test_protocol_has_no_implicit_default_thresholds() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    incomplete = {
        "artifactVersion": service.PROTOCOL_VERSION,
        "protocolId": "promotion-protocol-002",
        "registeredAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "researchGateFingerprint": "gate-abc",
        "requiredHorizons": [7],
        "criteriaByHorizon": {},
    }

    with pytest.raises(ValueError, match="Faltan criterios precomprometidos"):
        service.fingerprint_protocol(incomplete)

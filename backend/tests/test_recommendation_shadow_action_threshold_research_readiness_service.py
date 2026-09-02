from __future__ import annotations

import pytest

from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_shadow_action_threshold_research_readiness_service import (
    RecommendationShadowActionThresholdResearchReadinessService,
)


class _EvidenceService:
    def __init__(self, payload):
        self.payload = payload
        self.received = []

    def assess(self, split):
        self.received.append(split)
        return self.payload


def _split():
    return {"splitFingerprint": "a" * 64}


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=1.5,
        slippage_bps=2.0,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )


def _evidence(*, ready_30=True, ready_90=True):
    return {
        "sourceSplitFingerprint": "a" * 64,
        "evidenceFingerprint": "b" * 64,
        "requestedHorizons": [30, 90],
        "horizons": {
            "30": {
                "evidenceSufficientForThresholdResearch": ready_30,
                "validationSupportsSignalDiscrimination": ready_30,
            },
            "90": {
                "evidenceSufficientForThresholdResearch": ready_90,
                "validationSupportsSignalDiscrimination": ready_90,
            },
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "futureReserveConsumed": False,
            "thresholdFitting": "not_performed",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def test_readiness_requires_all_requested_horizons_to_pass():
    evidence_service = _EvidenceService(_evidence())
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=evidence_service
    )
    split = _split()

    result = service.assess(split=split, economic_contract=_contract())

    assert evidence_service.received == [split]
    assert result["status"] == "shadow_action_threshold_research_ready"
    assert result["thresholdResearchReadyHorizons"] == [30, 90]
    assert result["allRequestedHorizonsReadyForThresholdResearch"] is True
    assert result["productionEligible"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["actionThresholds"] is None
    assert result["policy"]["futureReserveConsumed"] is False
    assert result["policy"]["thresholdFitting"] == "not_performed"


def test_readiness_blocks_partial_multi_horizon_evidence_instead_of_cherry_picking():
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(_evidence(ready_90=False))
    )

    result = service.assess(split=_split(), economic_contract=_contract())

    assert result["status"] == "shadow_action_threshold_research_blocked"
    assert result["thresholdResearchReadyHorizons"] == [30]
    assert result["allRequestedHorizonsReadyForThresholdResearch"] is False
    assert result["blockedHorizons"]["90"] == [
        "insufficient_calibration_evidence",
        "validation_does_not_support_signal_discrimination",
    ]


def test_readiness_rejects_evidence_from_another_split():
    evidence = _evidence()
    evidence["sourceSplitFingerprint"] = "c" * 64
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(evidence)
    )

    with pytest.raises(ValueError, match="no corresponde"):
        service.assess(split=_split(), economic_contract=_contract())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("actionThresholds", {"buy": 0.03}),
        ("action", "buy"),
        ("score", 0.8),
        ("conviction", 0.7),
    ],
)
def test_readiness_fails_closed_if_evidence_attempts_promotion(field, value):
    evidence = _evidence()
    evidence[field] = value
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(evidence)
    )

    with pytest.raises(ValueError):
        service.assess(split=_split(), economic_contract=_contract())


def test_readiness_rejects_consumed_future_reserve():
    evidence = _evidence()
    evidence["policy"]["futureReserveConsumed"] = True
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(evidence)
    )

    with pytest.raises(ValueError, match="reserva temporal"):
        service.assess(split=_split(), economic_contract=_contract())


def test_readiness_rejects_tampered_economic_contract():
    contract = _contract()
    contract["actions"]["sell"]["allowedFrom"] = ["flat", "long"]
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(_evidence())
    )

    with pytest.raises(ValueError, match="fingerprint"):
        service.assess(split=_split(), economic_contract=contract)


def test_readiness_fingerprint_changes_when_cost_contract_changes():
    service = RecommendationShadowActionThresholdResearchReadinessService(
        evidence_service=_EvidenceService(_evidence())
    )
    first = service.assess(split=_split(), economic_contract=_contract())
    different_contract = RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=2.5,
        slippage_bps=2.0,
        objective_name="net_excess_return_after_explicit_costs",
        objective_version="v1",
    )
    second = service.assess(split=_split(), economic_contract=different_contract)

    assert first["economicContractFingerprint"] != second["economicContractFingerprint"]
    assert first["readinessFingerprint"] != second["readinessFingerprint"]

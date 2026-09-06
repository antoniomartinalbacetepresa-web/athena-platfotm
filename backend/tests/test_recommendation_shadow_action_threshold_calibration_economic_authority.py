from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_action_threshold_calibration_pipeline_service import (
    RecommendationShadowActionThresholdCalibrationPipelineService,
)


class _SplitService:
    def build(self, **kwargs):
        return {"splitFingerprint": "a" * 64}


class _RecordingAuthority:
    def __init__(self) -> None:
        self.artifacts: list[dict[str, object]] = []

    def seal(self, *, artifact):
        self.artifacts.append(deepcopy(artifact))
        return artifact


class _FailingAuthority:
    def seal(self, *, artifact):
        raise ValueError("authority unavailable")


class _SubstitutingAuthority:
    def seal(self, *, artifact):
        substituted = deepcopy(artifact)
        substituted["economicContractFingerprint"] = "f" * 64
        return substituted


class _BlockedReadiness:
    def __init__(self) -> None:
        self.calls = 0
        self.contracts: list[dict[str, object]] = []

    def assess(self, *, split, economic_contract):
        self.calls += 1
        self.contracts.append(deepcopy(economic_contract))
        return {
            "sourceSplitFingerprint": split["splitFingerprint"],
            "economicContractFingerprint": economic_contract["economicContractFingerprint"],
            "readinessFingerprint": "b" * 64,
            "requestedHorizons": [7, 30, 90, 180, 365],
            "blockedHorizons": [7, 30, 90, 180, 365],
            "allRequestedHorizonsReadyForThresholdResearch": False,
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
            },
        }


def _run(service: RecommendationShadowActionThresholdCalibrationPipelineService):
    return service.run(
        train_end=datetime(2024, 1, 1, tzinfo=timezone.utc),
        validation_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        transaction_cost_bps=10.0,
        slippage_bps=5.0,
        reduced_exposure_fraction=0.5,
        objective_name="net_excess_return_after_costs",
        objective_version="v1",
    )


def test_pipeline_seals_exact_contract_before_readiness_even_when_evidence_blocks():
    authority = _RecordingAuthority()
    readiness = _BlockedReadiness()
    service = RecommendationShadowActionThresholdCalibrationPipelineService(
        split_service=_SplitService(),
        economic_contract_authority=authority,
        readiness_service=readiness,
    )

    result = _run(service)

    assert result["status"] == "shadow_action_threshold_calibration_blocked_by_evidence"
    assert len(authority.artifacts) == 1
    assert readiness.calls == 1
    assert authority.artifacts[0] == readiness.contracts[0] == result["economicContract"]
    assert result["economicContractFingerprint"] == result["economicContract"][
        "economicContractFingerprint"
    ]
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["economicContract"]["constraints"]["automaticTrading"] is False


def test_pipeline_fails_closed_before_readiness_when_authority_cannot_seal():
    readiness = _BlockedReadiness()
    service = RecommendationShadowActionThresholdCalibrationPipelineService(
        split_service=_SplitService(),
        economic_contract_authority=_FailingAuthority(),
        readiness_service=readiness,
    )

    with pytest.raises(ValueError, match="authority unavailable"):
        _run(service)

    assert readiness.calls == 0


def test_pipeline_rejects_authority_that_substitutes_contract_fingerprint():
    readiness = _BlockedReadiness()
    service = RecommendationShadowActionThresholdCalibrationPipelineService(
        split_service=_SplitService(),
        economic_contract_authority=_SubstitutingAuthority(),
        readiness_service=readiness,
    )

    with pytest.raises(ValueError, match="sustituyó el fingerprint"):
        _run(service)

    assert readiness.calls == 0

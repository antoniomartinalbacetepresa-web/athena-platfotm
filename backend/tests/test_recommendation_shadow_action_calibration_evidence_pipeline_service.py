from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_action_calibration_evidence_pipeline_service import (
    RecommendationShadowActionCalibrationEvidencePipelineService,
)


class _SplitService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class _EvidenceService:
    def __init__(self, payload):
        self.payload = payload
        self.received = []

    def assess(self, split):
        self.received.append(split)
        return self.payload


def _split():
    return {
        "splitFingerprint": "a" * 64,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {"futureReserveConsumed": False},
    }


def _evidence():
    return {
        "sourceSplitFingerprint": "a" * 64,
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


def test_pipeline_passes_only_producer_split_to_evidence_gate():
    split = _split()
    evidence = _evidence()
    split_service = _SplitService(split)
    evidence_service = _EvidenceService(evidence)
    service = RecommendationShadowActionCalibrationEvidencePipelineService(
        split_service=split_service,
        evidence_service=evidence_service,
    )
    train_end = datetime(2026, 3, 31, tzinfo=timezone.utc)
    validation_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    as_of = datetime(2026, 9, 1, tzinfo=timezone.utc)

    result = service.evaluate(
        train_end=train_end,
        validation_end=validation_end,
        as_of=as_of,
        symbol="TEST",
        horizons=(30, 90),
    )

    assert result is evidence
    assert evidence_service.received == [split]
    assert split_service.calls == [
        {
            "train_end": train_end,
            "validation_end": validation_end,
            "as_of": as_of,
            "symbol": "TEST",
            "horizons": (30, 90),
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("productionEligible", True, "producción"),
        ("recommendationCandidateReady", True, "recomendaciones"),
        ("actionThresholdCalibrationResearchEligible", True, "calibración"),
        ("action", "buy", "acción"),
        ("score", 0.9, "score/conviction"),
        ("actionThresholds", {"buy": 0.1}, "thresholds"),
    ],
)
def test_pipeline_fails_closed_if_evidence_attempts_promotion(field, value, message):
    evidence = _evidence()
    evidence[field] = value
    service = RecommendationShadowActionCalibrationEvidencePipelineService(
        split_service=_SplitService(_split()),
        evidence_service=_EvidenceService(evidence),
    )

    with pytest.raises(ValueError, match=message):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )


def test_pipeline_rejects_mismatched_source_split_fingerprint():
    evidence = _evidence()
    evidence["sourceSplitFingerprint"] = "b" * 64
    service = RecommendationShadowActionCalibrationEvidencePipelineService(
        split_service=_SplitService(_split()),
        evidence_service=_EvidenceService(evidence),
    )

    with pytest.raises(ValueError, match="no corresponde"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )


def test_pipeline_rejects_future_reserve_consumption_and_threshold_fitting():
    evidence = _evidence()
    evidence["policy"]["futureReserveConsumed"] = True
    service = RecommendationShadowActionCalibrationEvidencePipelineService(
        split_service=_SplitService(_split()),
        evidence_service=_EvidenceService(evidence),
    )
    with pytest.raises(ValueError, match="reserva temporal"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

    evidence = _evidence()
    evidence["policy"]["thresholdFitting"] = "performed"
    service = RecommendationShadowActionCalibrationEvidencePipelineService(
        split_service=_SplitService(_split()),
        evidence_service=_EvidenceService(evidence),
    )
    with pytest.raises(ValueError, match="ajustó thresholds"):
        service.evaluate(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

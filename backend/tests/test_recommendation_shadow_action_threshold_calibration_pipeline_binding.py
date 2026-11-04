from __future__ import annotations

import pytest

from app.services.recommendation_shadow_action_threshold_calibration_pipeline_service import (
    RecommendationShadowActionThresholdCalibrationPipelineService,
)


PANEL_FINGERPRINT = "b" * 64


def _service() -> RecommendationShadowActionThresholdCalibrationPipelineService:
    return RecommendationShadowActionThresholdCalibrationPipelineService.__new__(
        RecommendationShadowActionThresholdCalibrationPipelineService
    )


def _panel(*, fingerprint: str = PANEL_FINGERPRINT) -> dict[str, object]:
    return {
        "utilityPanelFingerprint": fingerprint,
        "validationUtilityRows": [{"candidateId": "candidate-1"}],
    }


def _freeze(*, source_fingerprint: str = PANEL_FINGERPRINT) -> dict[str, object]:
    return {
        "sourceUtilityPanelFingerprint": source_fingerprint,
        "status": "shadow_action_thresholds_frozen_before_future_confirmation",
        "registered": True,
        "futureReserveConfirmationEligible": True,
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
            "callerSuppliedSelectionTimestampAccepted": False,
        },
    }


def test_accepts_freeze_bound_to_exact_utility_panel():
    _service()._assert_freeze(
        panel=_panel(),
        freeze=_freeze(),
    )


def test_rejects_safe_looking_freeze_from_different_utility_panel():
    with pytest.raises(ValueError, match="no pertenece al panel"):
        _service()._assert_freeze(
            panel=_panel(),
            freeze=_freeze(source_fingerprint="c" * 64),
        )


def test_rejects_freeze_without_source_utility_panel_fingerprint():
    freeze = _freeze()
    del freeze["sourceUtilityPanelFingerprint"]

    with pytest.raises(ValueError, match="sourceUtilityPanelFingerprint"):
        _service()._assert_freeze(
            panel=_panel(),
            freeze=freeze,
        )

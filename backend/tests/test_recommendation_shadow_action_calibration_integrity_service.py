from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_action_calibration_integrity_service import (
    RecommendationShadowActionCalibrationIntegrityService,
)


def _row(candidate_id: int, candidate_as_of: str, evaluated_at: str):
    return {
        "candidateId": candidate_id,
        "horizonDays": 30,
        "symbol": "TEST",
        "candidateAsOf": candidate_as_of,
        "outcomeDueAt": "2026-02-01T00:00:00+00:00",
        "outcomeEvaluatedAt": evaluated_at,
    }


def _artifact():
    return {
        "artifactVersion": "shadow-action-calibration-split-v1",
        "trainEnd": "2026-03-31T00:00:00+00:00",
        "validationEnd": "2026-06-30T00:00:00+00:00",
        "asOf": "2026-09-01T00:00:00+00:00",
        "requestedHorizons": [30],
        "trainRowCount": 1,
        "validationRowCount": 1,
        "purgedTrainRowCount": 0,
        "purgedValidationRowCount": 0,
        "reservedFutureRowCount": 1,
        "trainRows": [
            _row(1, "2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00")
        ],
        "validationRows": [
            _row(2, "2026-04-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00")
        ],
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "ordering": "strict_chronological_no_random_shuffle",
            "purging": "labels_unknown_at_partition_boundary_are_excluded",
            "futureReserveConsumed": False,
            "thresholdFitting": "not_performed",
            "scoreCalibration": "not_performed",
            "convictionCalibration": "not_performed",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def test_accepts_semantically_valid_shadow_split():
    artifact = _artifact()
    assert RecommendationShadowActionCalibrationIntegrityService().validate(artifact) is artifact


def test_rejects_train_label_unknown_at_train_boundary():
    artifact = _artifact()
    artifact["trainRows"][0]["outcomeEvaluatedAt"] = "2026-04-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="train viola"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)


def test_rejects_validation_candidate_from_train_period():
    artifact = _artifact()
    artifact["validationRows"][0]["candidateAsOf"] = "2026-03-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="validation viola"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)


def test_rejects_duplicate_identity_across_partitions():
    artifact = _artifact()
    artifact["validationRows"][0]["candidateId"] = 1
    with pytest.raises(ValueError, match="más de una vez"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)


def test_rejects_unrequested_horizon_and_future_label():
    artifact = _artifact()
    artifact["validationRows"][0]["horizonDays"] = 90
    with pytest.raises(ValueError, match="horizonte no solicitado"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)

    artifact = _artifact()
    artifact["validationRows"][0]["outcomeEvaluatedAt"] = "2026-09-02T00:00:00+00:00"
    with pytest.raises(ValueError, match="después de asOf"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)


def test_rejects_count_tampering_and_shadow_promotion():
    artifact = _artifact()
    artifact["trainRowCount"] = 2
    with pytest.raises(ValueError, match="trainRowCount"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)

    artifact = _artifact()
    artifact["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)


def test_rejects_policy_that_consumes_future_reserve():
    artifact = copy.deepcopy(_artifact())
    artifact["policy"]["futureReserveConsumed"] = True
    with pytest.raises(ValueError, match="futureReserveConsumed"):
        RecommendationShadowActionCalibrationIntegrityService().validate(artifact)

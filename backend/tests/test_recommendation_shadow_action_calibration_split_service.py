from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_action_calibration_split_service import (
    RecommendationShadowActionCalibrationSplitService,
)


DATASET_FP = "a" * 64
ATTESTATION_FP = "b" * 64


class FakeDatasetService:
    def __init__(self, rows=None, payload=None):
        self.rows = list(rows or [])
        self.payload = payload
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        if self.payload is not None:
            return dict(self.payload)
        return _dataset(self.rows)


def _row(
    candidate_id: int,
    candidate_as_of: str,
    outcome_evaluated_at: str,
    *,
    horizon: int = 30,
):
    return {
        "candidateId": candidate_id,
        "candidateFingerprint": (hex(candidate_id)[2:][-1] or "c") * 64,
        "liveCycleAttestationFingerprint": ATTESTATION_FP,
        "decisionResearchFingerprint": "d" * 64,
        "uncertaintyFingerprint": "e" * 64,
        "symbol": "TEST",
        "candidateAsOf": candidate_as_of,
        "horizonDays": horizon,
        "expectedExcessReturn": 0.05,
        "researchStrength": 1.0,
        "conservativeResearchStrength": -0.2,
        "riskAdjustedResearchStrength": 0.8,
        "residualRmse": 0.05,
        "residualMae": 0.04,
        "uncertaintyObservationCount": 30,
        "lowerEmpiricalExcessReturn": -0.01,
        "medianEmpiricalExcessReturn": 0.04,
        "upperEmpiricalExcessReturn": 0.10,
        "pointEstimatePositive": True,
        "medianScenarioPositive": True,
        "lowerScenarioPositive": False,
        "upperScenarioNegative": False,
        "riskScore": 0.2,
        "annualizedVolatility": 0.25,
        "maxDrawdown60d": -0.1,
        "realizedExcessReturn": 0.03,
        "realizedReturn": 0.04,
        "benchmarkReturn": 0.01,
        "predictionError": 0.02,
        "directionCorrect": True,
        "outcomeDueAt": "2026-02-01T00:00:00+00:00",
        "outcomeEvaluatedAt": outcome_evaluated_at,
    }


def _dataset(rows):
    return {
        "status": "shadow_action_calibration_dataset_available",
        "datasetVersion": "shadow-action-calibration-v2",
        "datasetFingerprint": DATASET_FP,
        "symbol": "TEST",
        "requestedHorizons": [30],
        "rows": list(rows),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "evidenceSource": "trusted_persisted_live_cycle_attestation_v1_only",
            "researchHoldoutReuse": False,
        },
    }


def test_split_purges_labels_unknown_at_partition_boundary_and_hides_future_rows():
    rows = [
        _row(1, "2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00"),
        _row(2, "2026-01-10T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
        _row(3, "2026-04-10T00:00:00+00:00", "2026-05-20T00:00:00+00:00"),
        _row(4, "2026-05-10T00:00:00+00:00", "2026-07-01T00:00:00+00:00"),
        _row(5, "2026-07-10T00:00:00+00:00", "2026-08-15T00:00:00+00:00"),
    ]
    service = RecommendationShadowActionCalibrationSplitService(
        dataset_service=FakeDatasetService(rows=rows)
    )

    result = service.build(
        train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
        validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        horizons=[30],
    )

    assert result["status"] == "shadow_action_calibration_split_available"
    assert [row["candidateId"] for row in result["trainRows"]] == [1]
    assert [row["candidateId"] for row in result["validationRows"]] == [3]
    assert result["purgedTrainRowCount"] == 1
    assert result["purgedValidationRowCount"] == 1
    assert result["reservedFutureRowCount"] == 1
    assert all(row["candidateId"] != 5 for row in result["trainRows"] + result["validationRows"])
    assert result["policy"]["futureReserveConsumed"] is False
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert service.validate_artifact(result) is result


def test_split_requires_strict_aware_chronological_boundaries():
    service = RecommendationShadowActionCalibrationSplitService(
        dataset_service=FakeDatasetService(rows=[])
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.build(
            train_end=datetime(2026, 3, 31),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="train_end < validation_end < as_of"):
        service.build(
            train_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )


def test_split_rejects_dataset_without_trusted_live_provenance():
    payload = _dataset([])
    payload["policy"] = {
        "evidenceSource": "legacy_unattested",
        "researchHoldoutReuse": False,
    }
    service = RecommendationShadowActionCalibrationSplitService(
        dataset_service=FakeDatasetService(payload=payload)
    )

    with pytest.raises(ValueError, match="provenance"):
        service.build(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )


def test_split_rejects_duplicate_candidate_horizon_rows():
    duplicate = _row(1, "2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00")
    service = RecommendationShadowActionCalibrationSplitService(
        dataset_service=FakeDatasetService(rows=[duplicate, dict(duplicate)])
    )

    with pytest.raises(ValueError, match="duplicada"):
        service.build(
            train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
            validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )


def test_split_detects_artifact_tampering():
    service = RecommendationShadowActionCalibrationSplitService(
        dataset_service=FakeDatasetService(
            rows=[
                _row(1, "2026-01-01T00:00:00+00:00", "2026-02-02T00:00:00+00:00"),
                _row(2, "2026-04-01T00:00:00+00:00", "2026-05-02T00:00:00+00:00"),
            ]
        )
    )
    artifact = service.build(
        train_end=datetime(2026, 3, 31, tzinfo=timezone.utc),
        validation_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
        as_of=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    artifact["trainRows"][0]["realizedExcessReturn"] = 99.0

    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(artifact)

from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_action_calibration_evidence_service import (
    RecommendationShadowActionCalibrationEvidenceService,
)


class _FingerprintValidator:
    def __init__(self):
        self.calls = 0

    def validate_artifact(self, artifact):
        self.calls += 1
        return artifact


class _SemanticValidator:
    def __init__(self):
        self.calls = 0

    def validate(self, artifact):
        self.calls += 1
        return artifact


class _ReplacingFingerprintValidator:
    def validate_artifact(self, artifact):
        return dict(artifact)


class _FailingSemanticValidator:
    def validate(self, artifact):
        raise ValueError("semantic barrier failed")


def _rows(start_id: int, count: int, *, horizon: int = 30, aligned: bool = True):
    rows = []
    midpoint = count // 2
    for offset in range(count):
        expected = -0.20 + (0.40 * offset / max(1, count - 1))
        realized = expected if aligned else -expected
        if offset == midpoint and realized == 0.0:
            realized = 0.001 if aligned else -0.001
        rows.append(
            {
                "candidateId": start_id + offset,
                "horizonDays": horizon,
                "expectedExcessReturn": expected,
                "realizedExcessReturn": realized,
            }
        )
    return rows


def _split(*, train_count: int = 24, validation_count: int = 12, aligned: bool = True):
    return {
        "splitFingerprint": "a" * 64,
        "trainEnd": "2026-03-31T00:00:00+00:00",
        "validationEnd": "2026-06-30T00:00:00+00:00",
        "asOf": "2026-09-01T00:00:00+00:00",
        "requestedHorizons": [30],
        "trainRows": _rows(1, train_count, aligned=True),
        "validationRows": _rows(100, validation_count, aligned=aligned),
    }


def _service(**kwargs):
    fingerprint = kwargs.pop("fingerprint_validator", _FingerprintValidator())
    semantic = kwargs.pop("semantic_validator", _SemanticValidator())
    return RecommendationShadowActionCalibrationEvidenceService(
        fingerprint_validator=fingerprint,
        semantic_validator=semantic,
        **kwargs,
    ), fingerprint, semantic


def test_assesses_signal_discrimination_without_fitting_actions_or_thresholds():
    service, fingerprint, semantic = _service()

    result = service.assess(_split())

    assert fingerprint.calls == 1
    assert semantic.calls == 1
    assert result["status"] == "shadow_action_calibration_evidence_available"
    assert result["evidenceSufficientHorizonCount"] == 1
    assert result["validationSupportHorizonCount"] == 1
    horizon = result["horizons"]["30"]
    assert horizon["evidenceSufficientForThresholdResearch"] is True
    assert horizon["validationSupportsSignalDiscrimination"] is True
    assert horizon["train"]["spearmanCorrelation"] == pytest.approx(1.0)
    assert horizon["validation"]["tailRealizedSpread"] > 0.0
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["productionEligible"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["policy"]["futureReserveConsumed"] is False
    assert result["policy"]["economicUtilityAssumptionsInvented"] is False
    assert len(result["evidenceFingerprint"]) == 64


def test_validation_can_reject_signal_even_when_train_is_perfect():
    service, _, _ = _service()

    result = service.assess(_split(aligned=False))

    horizon = result["horizons"]["30"]
    assert horizon["evidenceSufficientForThresholdResearch"] is True
    assert horizon["validationSupportsSignalDiscrimination"] is False
    assert "nonpositive_validation_rank_correlation" in horizon["validationSupportReasons"]
    assert "nonpositive_validation_tail_spread" in horizon["validationSupportReasons"]
    assert result["validationSupportHorizonCount"] == 0


def test_insufficient_or_one_sided_outcomes_are_not_silently_treated_as_ready():
    service, _, _ = _service(min_train_rows=20, min_validation_rows=10)
    split = _split(train_count=8, validation_count=6)
    for row in split["trainRows"] + split["validationRows"]:
        row["realizedExcessReturn"] = abs(row["realizedExcessReturn"]) + 0.01

    result = service.assess(split)

    horizon = result["horizons"]["30"]
    assert horizon["evidenceSufficientForThresholdResearch"] is False
    assert "insufficient_train_rows" in horizon["evidenceReasons"]
    assert "insufficient_validation_rows" in horizon["evidenceReasons"]
    assert "insufficient_train_negative_outcomes" in horizon["evidenceReasons"]
    assert "insufficient_validation_negative_outcomes" in horizon["evidenceReasons"]
    assert result["status"] == "shadow_action_calibration_evidence_insufficient"


def test_both_fingerprint_and_semantic_barriers_are_fail_closed():
    service = RecommendationShadowActionCalibrationEvidenceService(
        fingerprint_validator=_ReplacingFingerprintValidator(),
        semantic_validator=_SemanticValidator(),
    )
    with pytest.raises(ValueError, match="fingerprint sustituyó"):
        service.assess(_split())

    service = RecommendationShadowActionCalibrationEvidenceService(
        fingerprint_validator=_FingerprintValidator(),
        semantic_validator=_FailingSemanticValidator(),
    )
    with pytest.raises(ValueError, match="semantic barrier failed"):
        service.assess(_split())


def test_requested_horizons_must_be_unique_and_metrics_reject_nonfinite_values():
    service, _, _ = _service()
    split = _split()
    split["requestedHorizons"] = [30, 30]
    with pytest.raises(ValueError, match="duplicados"):
        service.assess(split)

    split = _split()
    split["validationRows"][0]["expectedExcessReturn"] = float("nan")
    with pytest.raises(ValueError, match="finito"):
        service.assess(split)


def test_evidence_fingerprint_changes_when_validation_evidence_changes():
    service, _, _ = _service()
    first = service.assess(_split())
    changed = _split()
    changed["validationRows"][0]["realizedExcessReturn"] += 0.05
    second = service.assess(changed)

    assert first["evidenceFingerprint"] != second["evidenceFingerprint"]
    assert first["sourceSplitFingerprint"] == second["sourceSplitFingerprint"]


def test_blocking_requirements_make_missing_economic_contract_explicit():
    service, _, _ = _service()
    result = service.assess(_split())

    assert "immutable_position_state_and_action_semantics_contract" in result[
        "blockingRequirementsBeforeActionThresholdFitting"
    ]
    assert "precommitted_transaction_cost_and_slippage_objective" in result[
        "blockingRequirementsBeforeActionThresholdFitting"
    ]
    assert result["policy"]["thresholdFitting"] == "not_performed"

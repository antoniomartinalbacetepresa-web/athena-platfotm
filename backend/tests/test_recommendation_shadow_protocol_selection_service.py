from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_protocol_selection_service import (
    RecommendationShadowProtocolSelectionService,
)


def _evaluation(ridge_lambda: float, *, horizon_days: int = 30):
    return {
        "status": "shadow_linear_candidate_evaluated",
        "horizonDays": horizon_days,
        "selection": {
            "criterion": "minimum_validation_mse",
            "ridgeLambda": ridge_lambda,
            "candidates": [
                {"ridgeLambda": 0.1, "validation": {"mse": 0.3}},
                {"ridgeLambda": 1.0, "validation": {"mse": 0.2}},
                {"ridgeLambda": 10.0, "validation": {"mse": 0.4}},
            ],
        },
        "test": {"mse": 999.0, "signAccuracy": 0.0},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _walk_forward(lambdas=(1.0, 1.0, 10.0, 1.0)):
    return {
        "status": "shadow_walk_forward_evaluated",
        "horizonDays": 30,
        "folds": [
            {
                "foldIndex": index,
                "evaluation": _evaluation(ridge_lambda),
            }
            for index, ridge_lambda in enumerate(lambdas)
        ],
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_selects_modal_validation_lambda_without_using_test_metrics():
    service = RecommendationShadowProtocolSelectionService()
    evidence = _walk_forward()

    result = service.select(walk_forward_evidence=evidence, horizon_days=30)

    assert result["status"] == "shadow_ridge_protocol_selected"
    assert result["selectedRidgeLambda"] == 1.0
    assert result["selectedFoldCount"] == 3
    assert result["evaluatedFoldSelectionCount"] == 4
    assert result["selectionSupportRatio"] == pytest.approx(0.75)
    assert result["testMetricsUsedForSelection"] is False
    assert result["productionEligible"] is False
    assert result["advisoryStatus"] == "no_advice"
    service.validate_selection(result)


def test_selection_is_unchanged_when_test_metrics_are_rewritten():
    service = RecommendationShadowProtocolSelectionService()
    first_evidence = _walk_forward()
    second_evidence = copy.deepcopy(first_evidence)
    for fold in second_evidence["folds"]:
        fold["evaluation"]["test"] = {
            "mse": 0.0000001 if fold["foldIndex"] % 2 else 10_000_000.0,
            "signAccuracy": 1.0,
        }

    first = service.select(walk_forward_evidence=first_evidence, horizon_days=30)
    second = service.select(walk_forward_evidence=second_evidence, horizon_days=30)

    assert first["selectedRidgeLambda"] == second["selectedRidgeLambda"] == 1.0
    assert first["selectionFingerprint"] == second["selectionFingerprint"]


def test_tie_breaks_toward_stronger_regularization_deterministically():
    service = RecommendationShadowProtocolSelectionService()

    result = service.select(
        walk_forward_evidence=_walk_forward((0.1, 0.1, 10.0, 10.0)),
        horizon_days=30,
    )

    assert result["tieCount"] == 2
    assert result["selectedRidgeLambda"] == 10.0
    service.validate_selection(result)


def test_insufficient_evaluated_folds_blocks_selection():
    service = RecommendationShadowProtocolSelectionService(minimum_evaluated_folds=3)
    evidence = _walk_forward((1.0, 1.0))

    result = service.select(walk_forward_evidence=evidence, horizon_days=30)

    assert result["status"] == "insufficient_protocol_selection_evidence"
    assert result["productionEligible"] is False


def test_validate_selection_detects_selected_lambda_tampering():
    service = RecommendationShadowProtocolSelectionService()
    result = service.select(walk_forward_evidence=_walk_forward(), horizon_days=30)
    result["selectedRidgeLambda"] = 10.0

    with pytest.raises(ValueError, match="regla determinista"):
        service.validate_selection(result)


def test_rejects_horizon_mismatch_and_non_shadow_evidence():
    service = RecommendationShadowProtocolSelectionService()

    with pytest.raises(ValueError, match="no coincide"):
        service.select(walk_forward_evidence=_walk_forward(), horizon_days=90)

    evidence = _walk_forward()
    evidence["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible"):
        service.select(walk_forward_evidence=evidence, horizon_days=30)

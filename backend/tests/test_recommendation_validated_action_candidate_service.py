import pytest

from app.services.recommendation_validated_action_candidate_service import (
    RecommendationValidatedActionCandidateService,
)


class _Validator:
    def validate_artifact(self, artifact):
        return artifact


class _DecisionRepository:
    def __init__(self):
        self.decision = {
            "decisionId": "action-decision-1",
            "decisionFingerprint": "1" * 64,
            "selectionFingerprint": "2" * 64,
            "modelFingerprintsByHorizon": {"30": "3" * 64},
            "policyFingerprintsByHorizonAndState": {
                "30": {
                    "flat": "4" * 64,
                    "reduced_long": "5" * 64,
                    "full_long": "6" * 64,
                }
            },
            "actionPromotionEvidenceAccepted": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "automaticTrading": False,
        }

    def get(self, *, decision_id):
        if decision_id != self.decision["decisionId"]:
            return None
        return {"decision": self.decision}

    def validate_record(self, record):
        return record


class _SelectionRepository:
    def __init__(self):
        def policy(state, fingerprint, thresholds):
            return {
                "currentState": state,
                "policyFingerprint": fingerprint,
                "thresholds": thresholds,
            }

        self.selection = {
            "selections": {
                "30": {
                    "states": {
                        "flat": {
                            "selectedPolicy": policy(
                                "flat", "4" * 64, {"buyAtOrAbove": 0.02}
                            )
                        },
                        "reduced_long": {
                            "selectedPolicy": policy(
                                "reduced_long",
                                "5" * 64,
                                {
                                    "sellAtOrBelow": -0.02,
                                    "buyAtOrAbove": 0.02,
                                },
                            )
                        },
                        "full_long": {
                            "selectedPolicy": policy(
                                "full_long",
                                "6" * 64,
                                {
                                    "sellAtOrBelow": -0.03,
                                    "reduceAtOrBelow": -0.01,
                                },
                            )
                        },
                    }
                }
            }
        }

    def get(self, *, selection_fingerprint):
        if selection_fingerprint != "2" * 64:
            return None
        return {"selection": self.selection}

    def validate_record(self, record):
        return record


def _live(signal=0.05):
    return {
        "candidateFingerprint": "7" * 64,
        "instrumentId": 99,
        "symbol": "TEST",
        "asOf": "2026-09-05T00:00:00+00:00",
        "horizons": {
            "30": {
                "expectedExcessReturn": signal,
                "modelFingerprint": "3" * 64,
            }
        },
    }


def _calibrated():
    return {
        "candidateFingerprint": "7" * 64,
        "calibratedCandidateFingerprint": "8" * 64,
        "instrumentId": 99,
        "horizons": {
            "30": {
                "calibrationEvidenceBound": True,
                "modelFingerprint": "3" * 64,
            }
        },
    }


def _state(state, *, present, shares):
    return {
        "instrumentId": 99,
        "policyState": state,
        "positionPresent": present,
        "shares": shares,
        "portfolioPolicyStateFingerprint": "9" * 64,
    }


def _service():
    return RecommendationValidatedActionCandidateService(
        action_decision_repository=_DecisionRepository(),
        selection_repository=_SelectionRepository(),
        live_candidate_service=_Validator(),
        calibrated_candidate_service=_Validator(),
        portfolio_state_service=_Validator(),
    )


def test_flat_state_can_generate_buy_candidate_without_enabling_production():
    result = _service().build(
        action_decision_id="action-decision-1",
        live_candidate=_live(0.05),
        calibrated_candidate=_calibrated(),
        portfolio_state=_state("flat", present=False, shares=0.0),
        horizon_days=30,
    )

    assert result["action"] == "buy"
    assert result["actionEvidenceReady"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_full_long_negative_signal_can_generate_reduce_candidate_only_with_position():
    result = _service().build(
        action_decision_id="action-decision-1",
        live_candidate=_live(-0.02),
        calibrated_candidate=_calibrated(),
        portfolio_state=_state("full_long", present=True, shares=10.0),
        horizon_days=30,
    )

    assert result["action"] == "reduce"
    assert result["productionEligible"] is False


def test_portfolio_instrument_must_match_live_candidate():
    state = _state("full_long", present=True, shares=10.0)
    state["instrumentId"] = 100

    with pytest.raises(ValueError, match="otro instrumento"):
        _service().build(
            action_decision_id="action-decision-1",
            live_candidate=_live(-0.02),
            calibrated_candidate=_calibrated(),
            portfolio_state=state,
            horizon_days=30,
        )


def test_calibrated_candidate_must_belong_to_original_live_candidate():
    calibrated = _calibrated()
    calibrated["candidateFingerprint"] = "a" * 64

    with pytest.raises(ValueError, match="no pertenece"):
        _service().build(
            action_decision_id="action-decision-1",
            live_candidate=_live(),
            calibrated_candidate=calibrated,
            portfolio_state=_state("flat", present=False, shares=0.0),
            horizon_days=30,
        )


def test_promoted_policy_fingerprint_must_match_frozen_selection():
    service = _service()
    service._decision_repository.decision["policyFingerprintsByHorizonAndState"]["30"][
        "flat"
    ] = "f" * 64

    with pytest.raises(ValueError, match="política congelada"):
        service.build(
            action_decision_id="action-decision-1",
            live_candidate=_live(),
            calibrated_candidate=_calibrated(),
            portfolio_state=_state("flat", present=False, shares=0.0),
            horizon_days=30,
        )

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_action_promotion_protocol_repository import (
    RecommendationActionPromotionProtocolRepository,
)
from app.services.recommendation_action_promotion_evidence_service import (
    RecommendationActionPromotionEvidenceService,
)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _draft(
    *,
    minimum_incremental: float = 0.01,
    maximum_regret: float = 0.10,
    minimum_future_rows: int = 25,
) -> dict:
    states = {
        state: {
            "minimumMeanIncrementalUtilityVsHold": minimum_incremental,
            "maximumMeanHindsightRegret": maximum_regret,
        }
        for state in ("flat", "reduced_long", "full_long")
    }
    return {
        "artifactVersion": "athena-action-promotion-protocol-v2",
        "protocolId": "action-protocol-001",
        "requiredHorizons": [30],
        "minimumFutureRowsByHorizon": {"30": minimum_future_rows},
        "criteriaByHorizonAndState": {"30": states},
    }


def _confirmation(
    *, incremental: float = 0.02, regret: float = 0.05, row_count: int = 30
) -> dict:
    states = {}
    for index, state in enumerate(("flat", "reduced_long", "full_long")):
        states[state] = {
            "rowCount": row_count,
            "selectedPolicyFingerprint": ("a" if index == 0 else "b" if index == 1 else "c") * 64,
            "meanNetRealizedExcessUtility": 0.03,
            "meanHoldNetRealizedExcessUtility": 0.01,
            "meanIncrementalUtilityVsHold": incremental,
            "meanHindsightRegret": regret,
            "nonHoldDecisionRate": 0.40,
            "actionCounts": {"hold": 18, "buy": 12},
        }
    core = {
        "artifactVersion": "shadow-action-threshold-future-confirmation-v1",
        "selectionFingerprint": "d" * 64,
        "selectionRegistrationFingerprint": "e" * 64,
        "economicContractFingerprint": "f" * 64,
        "selectedAt": "2099-01-01T00:00:00+00:00",
        "asOf": "2099-06-01T00:00:00+00:00",
        "requestedHorizons": [30],
        "minimumSourceRowsPerHorizon": 20,
        "eligibleSourceRowCounts": {"30": row_count},
        "horizons": {
            "30": {
                "horizonDays": 30,
                "sourceRowCount": row_count,
                "states": states,
            }
        },
    }
    return {
        "status": "shadow_action_threshold_future_confirmation_sealed",
        **core,
        "confirmationFingerprint": _fingerprint(core),
        "performanceMetricsExposed": True,
        "futureConfirmationEvaluated": True,
        "firstMatureEvaluationSealed": True,
        "futureConfirmationPassed": None,
        "formalStatisticalPromotionGateImplemented": False,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": {
            "thresholdRefitAllowed": False,
            "policyReselectionAllowed": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        },
    }


def _service(tmp_path, *, draft=None):
    repository = RecommendationActionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    record = repository.register(protocol_draft=draft or _draft())
    return RecommendationActionPromotionEvidenceService(repository), record, repository


def test_precommitted_action_protocol_can_mark_evidence_ready_without_enabling_advice(tmp_path):
    service, record, _ = _service(tmp_path)

    result = service.evaluate_registered(
        confirmation_artifact=_confirmation(),
        protocol_id=record["protocol_id"],
    )

    assert result["status"] == "action_promotion_evidence_ready"
    assert result["actionPromotionEvidenceReady"] is True
    assert result["horizons"]["30"]["minimumFutureRowsRequired"] == 25
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["allocation"] is None
    assert result["automaticProductionPromotion"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["codeDefaultPromotionThresholds"] is False
    assert result["policy"]["codeDefaultProductionSampleSize"] is False
    assert result["policy"]["researchMaturityCountIsNotProductionSufficiency"] is True
    assert result["policy"]["portfolioStateStillRequiredForReduceOrSell"] is True


def test_research_maturity_count_does_not_override_precommitted_production_sample_size(tmp_path):
    service, record, _ = _service(tmp_path, draft=_draft(minimum_future_rows=50))

    result = service.evaluate_registered(
        confirmation_artifact=_confirmation(row_count=30),
        protocol_id=record["protocol_id"],
    )

    assert result["status"] == "action_promotion_evidence_insufficient"
    assert result["actionPromotionEvidenceReady"] is False
    assert result["horizons"]["30"]["blockers"] == [
        "future_sample_below_precommitted_minimum"
    ]
    assert result["productionEligible"] is False


def test_protocol_must_explicitly_precommit_production_sample_size(tmp_path):
    repository = RecommendationActionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    draft = _draft()
    del draft["minimumFutureRowsByHorizon"]

    with pytest.raises(ValueError, match="minimumFutureRowsByHorizon"):
        repository.register(protocol_draft=draft)


def test_evidence_below_precommitted_utility_minimum_stays_blocked(tmp_path):
    service, record, _ = _service(tmp_path)

    result = service.evaluate_registered(
        confirmation_artifact=_confirmation(incremental=0.005),
        protocol_id=record["protocol_id"],
    )

    assert result["status"] == "action_promotion_evidence_insufficient"
    assert result["actionPromotionEvidenceReady"] is False
    assert result["productionEligible"] is False
    assert result["horizons"]["30"]["states"]["flat"]["blockers"] == [
        "incremental_utility_below_precommitted_minimum"
    ]


def test_protocol_registered_after_policy_freeze_fails_closed(tmp_path):
    service, record, _ = _service(tmp_path)
    confirmation = _confirmation()
    core_keys = (
        "artifactVersion",
        "selectionFingerprint",
        "selectionRegistrationFingerprint",
        "economicContractFingerprint",
        "selectedAt",
        "asOf",
        "requestedHorizons",
        "minimumSourceRowsPerHorizon",
        "eligibleSourceRowCounts",
        "horizons",
    )
    confirmation["selectedAt"] = "2000-01-01T00:00:00+00:00"
    confirmation["confirmationFingerprint"] = _fingerprint(
        {key: confirmation.get(key) for key in core_keys}
    )

    with pytest.raises(ValueError, match="después del freeze"):
        service.evaluate_registered(
            confirmation_artifact=confirmation,
            protocol_id=record["protocol_id"],
        )


def test_tampered_sealed_confirmation_fails_closed(tmp_path):
    service, record, _ = _service(tmp_path)
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["30"]["states"]["flat"][
        "meanIncrementalUtilityVsHold"
    ] = 999.0

    with pytest.raises(ValueError, match="modificada"):
        service.evaluate_registered(
            confirmation_artifact=confirmation,
            protocol_id=record["protocol_id"],
        )


def test_non_finite_protocol_criterion_is_rejected(tmp_path):
    repository = RecommendationActionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    draft = _draft()
    draft["criteriaByHorizonAndState"]["30"]["flat"][
        "minimumMeanIncrementalUtilityVsHold"
    ] = float("nan")

    with pytest.raises(ValueError, match="finito"):
        repository.register(protocol_draft=draft)


def test_registered_protocol_is_immutable_and_caller_cannot_backdate(tmp_path):
    repository = RecommendationActionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    draft = _draft()
    record = repository.register(protocol_draft=draft)

    assert record["protocol"]["registeredAt"] == record["registered_at"]
    assert record["protocol"]["protocolFingerprint"] == record["protocol_fingerprint"]

    backdated = _draft()
    backdated["registeredAt"] = "1900-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="los genera el registro"):
        repository.register(protocol_draft=backdated)

    changed = _draft(minimum_incremental=0.50)
    with pytest.raises(ValueError, match="inmutables"):
        repository.register(protocol_draft=changed)

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_allocation_candidate_service import (
    RecommendationAllocationCandidateService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_verified_allocation_pipeline_service import (
    RecommendationVerifiedAllocationPipelineService,
)


AS_OF = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
VALUATION_FP = "c" * 64
VALUATION_RECORD_FP = "d" * 64
ACTION_RECORD_FP = "e" * 64
POLICY_FP = "b" * 64


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=5.0,
        slippage_bps=3.0,
        reduced_exposure_fraction=0.40,
        objective_name="test",
        objective_version="v1",
    )


def _action(*, instrument_id=10, state="flat", action="buy", as_of=AS_OF, economic_contract_fingerprint=None):
    if economic_contract_fingerprint is None:
        economic_contract_fingerprint = _contract()["economicContractFingerprint"]
    core = {
        "artifactVersion": "athena-uncertainty-bound-action-candidate-v1",
        "validatedActionCandidateFingerprint": "1" * 64,
        "actionUncertaintyEvidenceFingerprint": "2" * 64,
        "actionPromotionDecisionId": "decision-001",
        "actionPromotionDecisionFingerprint": "3" * 64,
        "economicContractFingerprint": economic_contract_fingerprint,
        "candidateFingerprint": "4" * 64,
        "instrumentId": instrument_id,
        "symbol": "AAA",
        "asOf": as_of.isoformat(),
        "horizonDays": 30,
        "modelFingerprint": "5" * 64,
        "policyState": state,
        "policyFingerprint": "6" * 64,
        "portfolioPolicyStateFingerprint": "7" * 64,
        "action": action,
    }
    return {
        "status": "uncertainty_bound_action_candidate_non_advisory",
        **core,
        "uncertaintyBoundActionCandidateFingerprint": _fingerprint(core),
        "uncertaintyBoundActionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


class _PolicyRepository:
    def get(self, *, policy_id):
        if policy_id != "allocation-001":
            return None
        return {"policy": {"policyId": "allocation-001", "policyFingerprint": POLICY_FP, "baseCurrency": "EUR", "maximumInstrumentSleeveWeight": 0.10, "minimumCashReserveWeight": 0.20, "maximumAbsolutePairCorrelation": 0.70, "minimumCorrelationSampleCount": 30, "maximumCorrelationAgeSeconds": 172800}}

    def validate_record(self, record):
        return record


class _ContractValidator:
    def __init__(self, contract):
        self.contract = contract

    def validate(self, artifact):
        assert artifact is self.contract
        return artifact


class _ActionRepository:
    def __init__(self, artifact=None, *, substitute=False):
        self.artifact = artifact
        self.substitute = substitute

    def get(self, *, candidate_fingerprint):
        if self.artifact is None or self.artifact["uncertaintyBoundActionCandidateFingerprint"] != candidate_fingerprint:
            return None
        return {
            "candidate_fingerprint": candidate_fingerprint,
            "decision_id": self.artifact["actionPromotionDecisionId"],
            "decision_fingerprint": self.artifact["actionPromotionDecisionFingerprint"],
            "instrument_id": self.artifact["instrumentId"],
            "as_of": self.artifact["asOf"],
            "artifact": deepcopy(self.artifact),
            "persisted_at": "2026-09-01T11:59:00+00:00",
            "record_fingerprint": ACTION_RECORD_FP,
        }

    def validate_record(self, record):
        return deepcopy(record) if self.substitute else record


class _ValuationService:
    def __init__(self, artifact):
        self.artifact = artifact

    def build(self, *, positions, base_currency, as_of):
        return deepcopy(self.artifact)

    def validate_artifact(self, artifact):
        return artifact


class _ValuationRepository:
    def __init__(self, *, persisted_artifact=None, substitute=False):
        self.persisted_artifact = persisted_artifact
        self.substitute = substitute

    def seal(self, *, artifact):
        return {
            "valuation_fingerprint": artifact["portfolioValuationEvidenceFingerprint"],
            "as_of": artifact["asOf"],
            "base_currency": artifact["baseCurrency"],
            "artifact": deepcopy(artifact if self.persisted_artifact is None else self.persisted_artifact),
            "persisted_at": "2026-09-01T12:00:01+00:00",
            "record_fingerprint": VALUATION_RECORD_FP,
        }

    def validate_record(self, record):
        return deepcopy(record) if self.substitute else record


def _valuation(*, positions=None, total=None):
    rows = positions or []
    computed = sum(item["positionValueInBaseCurrency"] for item in rows)
    return {
        "status": "portfolio_valuation_evidence_verified_non_advisory",
        "artifactVersion": "athena-portfolio-valuation-evidence-v1",
        "asOf": AS_OF.isoformat(),
        "baseCurrency": "EUR",
        "valuationScope": "invested_long_positions_only_cash_liabilities_unsettled_excluded",
        "cashIncluded": False,
        "liabilitiesIncluded": False,
        "positionCount": len(rows),
        "positions": rows,
        "investedPositionsValueInBaseCurrency": computed if total is None else total,
        "portfolioValuationEvidenceFingerprint": VALUATION_FP,
        "portfolioValuationEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "automaticTrading": False,
    }


def _pipeline(valuation, *, action_artifact=None, action_repository=None, valuation_repository=None):
    contract = _contract()
    action = action_artifact or _action(economic_contract_fingerprint=contract["economicContractFingerprint"])
    allocation = RecommendationAllocationCandidateService(
        policy_repository=_PolicyRepository(),
        economic_contract_validator=_ContractValidator(contract),
    )
    return RecommendationVerifiedAllocationPipelineService(
        valuation_service=_ValuationService(valuation),
        valuation_repository=valuation_repository or _ValuationRepository(),
        action_repository=action_repository or _ActionRepository(action),
        allocation_service=allocation,
    ), contract, action


def _build(pipeline, contract, action, **overrides):
    params = dict(
        uncertainty_bound_action_candidate_fingerprint=action["uncertaintyBoundActionCandidateFingerprint"],
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        positions=[],
        correlation_evidence=[],
        as_of=AS_OF,
    )
    params.update(overrides)
    return pipeline.build(**params)


def test_flat_buy_requires_sealed_action_and_sealed_valuation():
    valuation = _valuation(positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 12000.0}])
    pipeline, contract, action = _pipeline(valuation)
    correlation = {"leftInstrumentId": 10, "rightInstrumentId": 20, "sourceProvider": "YAHOO_CHART", "knowledgeCutoff": AS_OF.isoformat(), "sampleCount": 60, "correlation": 0.30, "firstReturnDate": "2026-06-01", "lastReturnDate": "2026-08-31", "latestRetrievedAt": "2026-09-01T11:00:00+00:00"}

    result = _build(pipeline, contract, action, correlation_evidence=[correlation])

    allocation = result["allocationCandidate"]
    assert result["callerSuppliedActionArtifactsAccepted"] is False
    assert result["actionAuthorityBoundToAllocation"] is True
    assert result["uncertaintyBoundActionRecordFingerprint"] == ACTION_RECORD_FP
    assert result["portfolioValuationSealedBeforeAllocation"] is True
    assert result["portfolioValuationRecordFingerprint"] == VALUATION_RECORD_FP
    assert result["investedPositionsValueInBaseCurrency"] == 12000.0
    assert allocation["excessOverReferenceCapital"] == 2000.0
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_unregistered_action_fingerprint_fails_closed_before_valuation():
    valuation = _valuation()
    missing = _ActionRepository(None)
    pipeline, contract, action = _pipeline(valuation, action_repository=missing)
    with pytest.raises(ValueError, match="no está sellado"):
        _build(pipeline, contract, action)


def test_action_repository_cannot_substitute_record():
    valuation = _valuation()
    action = _action()
    pipeline, contract, action = _pipeline(valuation, action_artifact=action, action_repository=_ActionRepository(action, substitute=True))
    with pytest.raises(ValueError, match="sustituyó el registro de acción"):
        _build(pipeline, contract, action)


def test_reduce_derives_real_position_value_from_verified_valuation():
    action = _action(state="full_long", action="reduce")
    valuation = _valuation(positions=[{"instrumentId": 10, "positionValueInBaseCurrency": 1000.0}, {"instrumentId": 20, "positionValueInBaseCurrency": 8000.0}])
    pipeline, contract, action = _pipeline(valuation, action_artifact=action)
    result = _build(pipeline, contract, action)
    assert result["currentPositionValueInBaseCurrency"] == 1000.0
    assert result["allocationCandidate"]["deltaAmountInBaseCurrency"] == pytest.approx(-600.0)


def test_sell_fails_closed_without_real_target_position():
    action = _action(state="reduced_long", action="sell")
    valuation = _valuation(positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 9000.0}])
    pipeline, contract, action = _pipeline(valuation, action_artifact=action)
    with pytest.raises(ValueError, match="posición real"):
        _build(pipeline, contract, action)


def test_candidate_as_of_must_match_valuation_cutoff_exactly():
    other_as_of = datetime(2026, 9, 1, 11, 59, 59, tzinfo=timezone.utc)
    action = _action(as_of=other_as_of)
    pipeline, contract, action = _pipeline(_valuation(), action_artifact=action)
    with pytest.raises(ValueError, match="compartir exactamente as_of"):
        _build(pipeline, contract, action)


def test_wrong_valuation_aggregate_is_rejected():
    valuation = _valuation(positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 8000.0}], total=9000.0)
    pipeline, contract, action = _pipeline(valuation)
    with pytest.raises(ValueError, match="agregada"):
        _build(pipeline, contract, action)


def test_persisted_valuation_must_match_validated_artifact():
    valuation = _valuation(positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 8000.0}])
    tampered = deepcopy(valuation)
    tampered["investedPositionsValueInBaseCurrency"] = 1.0
    pipeline, contract, action = _pipeline(valuation, valuation_repository=_ValuationRepository(persisted_artifact=tampered))
    with pytest.raises(ValueError, match="sellada difiere"):
        _build(pipeline, contract, action)

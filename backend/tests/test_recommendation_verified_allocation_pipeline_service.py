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
POLICY_FP = "b" * 64


def _fingerprint(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _action(*, instrument_id=10, state="flat", action="buy"):
    core = {
        "artifactVersion": "athena-uncertainty-bound-action-candidate-v1",
        "validatedActionCandidateFingerprint": "1" * 64,
        "actionUncertaintyEvidenceFingerprint": "2" * 64,
        "actionPromotionDecisionId": "decision-001",
        "actionPromotionDecisionFingerprint": "3" * 64,
        "candidateFingerprint": "4" * 64,
        "instrumentId": instrument_id,
        "symbol": "AAA",
        "asOf": AS_OF.isoformat(),
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


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=5.0,
        slippage_bps=3.0,
        reduced_exposure_fraction=0.40,
        objective_name="test",
        objective_version="v1",
    )


class _PolicyRepository:
    def get(self, *, policy_id):
        if policy_id != "allocation-001":
            return None
        return {
            "policy": {
                "policyId": "allocation-001",
                "policyFingerprint": POLICY_FP,
                "baseCurrency": "EUR",
                "maximumInstrumentSleeveWeight": 0.10,
                "minimumCashReserveWeight": 0.20,
                "maximumAbsolutePairCorrelation": 0.70,
                "minimumCorrelationSampleCount": 30,
                "maximumCorrelationAgeSeconds": 172800,
            }
        }

    def validate_record(self, record):
        return record


class _ContractValidator:
    def __init__(self, contract):
        self.contract = contract

    def validate(self, artifact):
        assert artifact is self.contract
        return artifact


class _ValuationService:
    def __init__(self, artifact):
        self.artifact = artifact
        self.calls = []

    def build(self, *, positions, base_currency, as_of):
        self.calls.append((deepcopy(positions), base_currency, as_of))
        return deepcopy(self.artifact)

    def validate_artifact(self, artifact):
        return artifact


class _ValuationRepository:
    def __init__(self, *, persisted_artifact=None, substitute_on_validate=False):
        self.persisted_artifact = persisted_artifact
        self.substitute_on_validate = substitute_on_validate
        self.seal_calls = 0

    def seal(self, *, artifact):
        self.seal_calls += 1
        persisted = deepcopy(
            artifact if self.persisted_artifact is None else self.persisted_artifact
        )
        return {
            "valuation_fingerprint": artifact["portfolioValuationEvidenceFingerprint"],
            "as_of": artifact["asOf"],
            "base_currency": artifact["baseCurrency"],
            "artifact": persisted,
            "persisted_at": "2026-09-01T12:00:01+00:00",
            "record_fingerprint": VALUATION_RECORD_FP,
        }

    def validate_record(self, record):
        if self.substitute_on_validate:
            return deepcopy(record)
        return record


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


def _pipeline(valuation, *, valuation_repository=None):
    contract = _contract()
    allocation = RecommendationAllocationCandidateService(
        policy_repository=_PolicyRepository(),
        economic_contract_validator=_ContractValidator(contract),
    )
    return (
        RecommendationVerifiedAllocationPipelineService(
            valuation_service=_ValuationService(valuation),
            valuation_repository=valuation_repository or _ValuationRepository(),
            allocation_service=allocation,
        ),
        contract,
    )


def test_flat_buy_derives_zero_target_position_and_portfolio_total_from_valuation():
    valuation = _valuation(
        positions=[
            {"instrumentId": 20, "positionValueInBaseCurrency": 12000.0}
        ]
    )
    pipeline, contract = _pipeline(valuation)
    correlation = {
        "leftInstrumentId": 10,
        "rightInstrumentId": 20,
        "sourceProvider": "YAHOO_CHART",
        "knowledgeCutoff": AS_OF.isoformat(),
        "sampleCount": 60,
        "correlation": 0.30,
        "firstReturnDate": "2026-06-01",
        "lastReturnDate": "2026-08-31",
        "latestRetrievedAt": "2026-09-01T11:00:00+00:00",
    }

    result = pipeline.build(
        uncertainty_bound_action_candidate=_action(),
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        positions=[{"callerRawPosition": True}],
        correlation_evidence=[correlation],
        as_of=AS_OF,
    )

    allocation = result["allocationCandidate"]
    assert result["callerSuppliedValuationTotalsAccepted"] is False
    assert result["portfolioValuationBoundToAllocation"] is True
    assert result["portfolioValuationSealedBeforeAllocation"] is True
    assert result["portfolioValuationRecordFingerprint"] == VALUATION_RECORD_FP
    assert result["portfolioValuationPersistence"] == {
        "sealed": True,
        "persistedAt": "2026-09-01T12:00:01+00:00",
        "recordFingerprint": VALUATION_RECORD_FP,
    }
    assert result["investedPositionsValueInBaseCurrency"] == 12000.0
    assert result["currentPositionValueInBaseCurrency"] == 0.0
    assert result["existingPositionInstrumentIds"] == [20]
    assert allocation["currentPortfolioValueInBaseCurrency"] == 12000.0
    assert allocation["currentPositionValueInBaseCurrency"] == 0.0
    assert allocation["portfolioValuationEvidenceFingerprint"] == VALUATION_FP
    assert allocation["excessOverReferenceCapital"] == 2000.0
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_reduce_derives_real_position_value_and_held_ids_from_valuation():
    valuation = _valuation(
        positions=[
            {"instrumentId": 10, "positionValueInBaseCurrency": 1000.0},
            {"instrumentId": 20, "positionValueInBaseCurrency": 8000.0},
        ]
    )
    pipeline, contract = _pipeline(valuation)

    result = pipeline.build(
        uncertainty_bound_action_candidate=_action(state="full_long", action="reduce"),
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        positions=[],
        correlation_evidence=[],
        as_of=AS_OF,
    )

    allocation = result["allocationCandidate"]
    assert result["currentPositionValueInBaseCurrency"] == 1000.0
    assert result["existingPositionInstrumentIds"] == [10, 20]
    assert allocation["deltaAmountInBaseCurrency"] == pytest.approx(-600.0)


def test_sell_fails_closed_when_verified_valuation_has_no_real_target_position():
    valuation = _valuation(
        positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 9000.0}]
    )
    pipeline, contract = _pipeline(valuation)

    with pytest.raises(ValueError, match="posición real"):
        pipeline.build(
            uncertainty_bound_action_candidate=_action(
                state="reduced_long", action="sell"
            ),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_candidate_as_of_must_match_valuation_cutoff_exactly():
    valuation = _valuation()
    pipeline, contract = _pipeline(valuation)
    candidate = _action()
    candidate["asOf"] = "2026-09-01T11:59:59+00:00"

    with pytest.raises(ValueError, match="compartir exactamente as_of"):
        pipeline.build(
            uncertainty_bound_action_candidate=candidate,
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_self_consistent_but_wrong_aggregate_from_valuation_is_rejected():
    valuation = _valuation(
        positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 8000.0}],
        total=9000.0,
    )
    pipeline, contract = _pipeline(valuation)

    with pytest.raises(ValueError, match="agregada"):
        pipeline.build(
            uncertainty_bound_action_candidate=_action(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_production_escape_from_valuation_fails_closed_before_allocation():
    valuation = _valuation()
    valuation["productionEligible"] = True
    pipeline, contract = _pipeline(valuation)

    with pytest.raises(ValueError, match="producción"):
        pipeline.build(
            uncertainty_bound_action_candidate=_action(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_persisted_valuation_must_match_exact_validated_artifact():
    valuation = _valuation(
        positions=[{"instrumentId": 20, "positionValueInBaseCurrency": 8000.0}]
    )
    tampered = deepcopy(valuation)
    tampered["investedPositionsValueInBaseCurrency"] = 1.0
    repository = _ValuationRepository(persisted_artifact=tampered)
    pipeline, contract = _pipeline(valuation, valuation_repository=repository)

    with pytest.raises(ValueError, match="sellada difiere"):
        pipeline.build(
            uncertainty_bound_action_candidate=_action(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_repository_cannot_substitute_validated_sealed_record():
    valuation = _valuation()
    repository = _ValuationRepository(substitute_on_validate=True)
    pipeline, contract = _pipeline(valuation, valuation_repository=repository)

    with pytest.raises(ValueError, match="sustituyó el registro"):
        pipeline.build(
            uncertainty_bound_action_candidate=_action(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            positions=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )

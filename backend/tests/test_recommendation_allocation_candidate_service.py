from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.services.recommendation_allocation_candidate_service import (
    RecommendationAllocationCandidateService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


AS_OF = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
ACTION_FP = "a" * 64
POLICY_FP = "b" * 64
VALUATION_FP = "c" * 64


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


def _action_candidate(*, state="flat", action="buy") -> dict:
    core = {
        "artifactVersion": "athena-uncertainty-bound-action-candidate-v1",
        "validatedActionCandidateFingerprint": "1" * 64,
        "actionUncertaintyEvidenceFingerprint": "2" * 64,
        "actionPromotionDecisionId": "decision-001",
        "actionPromotionDecisionFingerprint": "3" * 64,
        "candidateFingerprint": "4" * 64,
        "instrumentId": 10,
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


def _allocation_policy() -> dict:
    return {
        "policyId": "allocation-001",
        "policyFingerprint": POLICY_FP,
        "baseCurrency": "EUR",
        "maximumInstrumentSleeveWeight": 0.10,
        "minimumCashReserveWeight": 0.20,
        "maximumAbsolutePairCorrelation": 0.70,
        "minimumCorrelationSampleCount": 30,
        "maximumCorrelationAgeSeconds": 172800,
    }


class _PolicyRepository:
    def get(self, *, policy_id):
        if policy_id != "allocation-001":
            return None
        return {"policy": _allocation_policy()}

    def validate_record(self, record):
        return record


class _ContractValidator:
    def __init__(self, contract):
        self.contract = contract

    def validate(self, artifact):
        assert artifact is self.contract
        return artifact


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=5.0,
        slippage_bps=3.0,
        reduced_exposure_fraction=0.40,
        objective_name="test",
        objective_version="v1",
    )


def _service(contract):
    return RecommendationAllocationCandidateService(
        policy_repository=_PolicyRepository(),
        economic_contract_validator=_ContractValidator(contract),
    )


def _correlation(other_id=20, *, correlation=0.30, sample_count=60, last_date="2026-08-31"):
    return {
        "leftInstrumentId": 10,
        "rightInstrumentId": other_id,
        "sourceProvider": "YAHOO_CHART",
        "knowledgeCutoff": AS_OF.isoformat(),
        "sampleCount": sample_count,
        "correlation": correlation,
        "firstReturnDate": "2026-06-01",
        "lastReturnDate": last_date,
        "latestRetrievedAt": "2026-09-01T11:00:00+00:00",
    }


def test_flat_buy_uses_portfolio_sleeve_not_single_asset_one_and_shows_excess():
    contract = _contract()
    result = _service(contract).build(
        uncertainty_bound_action_candidate=_action_candidate(),
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        current_portfolio_value_base=12000.0,
        current_position_value_base=0.0,
        portfolio_valuation_evidence_fingerprint=VALUATION_FP,
        existing_position_instrument_ids=[20],
        correlation_evidence=[_correlation()],
        as_of=AS_OF,
    )

    assert result["singleAssetTargetExposureFraction"] == 1.0
    assert result["targetWeight"] == 0.10
    assert result["targetAmountInBaseCurrency"] == 1000.0
    assert result["excessOverReferenceCapital"] == 2000.0
    assert result["shortfallVsReferenceCapital"] == 0.0
    assert result["correlationChecks"][0]["passesPolicy"] is True
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_full_long_reduce_scales_sleeve_and_does_not_require_correlation():
    contract = _contract()
    result = _service(contract).build(
        uncertainty_bound_action_candidate=_action_candidate(
            state="full_long", action="reduce"
        ),
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        current_portfolio_value_base=9000.0,
        current_position_value_base=1000.0,
        portfolio_valuation_evidence_fingerprint=VALUATION_FP,
        existing_position_instrument_ids=[10, 20],
        correlation_evidence=[],
        as_of=AS_OF,
    )

    assert result["singleAssetTargetExposureFraction"] == 0.40
    assert result["targetWeight"] == pytest.approx(0.04)
    assert result["targetAmountInBaseCurrency"] == pytest.approx(400.0)
    assert result["deltaAmountInBaseCurrency"] == pytest.approx(-600.0)
    assert result["correlationChecks"] == []
    assert result["policy"]["deRiskingNeverBlockedByMissingCorrelation"] is True


def test_sell_requires_real_position_and_targets_zero():
    contract = _contract()
    result = _service(contract).build(
        uncertainty_bound_action_candidate=_action_candidate(
            state="reduced_long", action="sell"
        ),
        allocation_policy_id="allocation-001",
        economic_contract=contract,
        reference_capital=10000.0,
        base_currency="EUR",
        current_portfolio_value_base=10000.0,
        current_position_value_base=400.0,
        portfolio_valuation_evidence_fingerprint=VALUATION_FP,
        existing_position_instrument_ids=[10],
        correlation_evidence=[],
        as_of=AS_OF,
    )
    assert result["targetWeight"] == 0.0
    assert result["deltaAmountInBaseCurrency"] == -400.0

    with pytest.raises(ValueError, match="posición real"):
        _service(contract).build(
            uncertainty_bound_action_candidate=_action_candidate(
                state="reduced_long", action="sell"
            ),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            current_portfolio_value_base=10000.0,
            current_position_value_base=0.0,
            portfolio_valuation_evidence_fingerprint=VALUATION_FP,
            existing_position_instrument_ids=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )


def test_increasing_exposure_fails_closed_without_each_verified_correlation():
    contract = _contract()
    with pytest.raises(ValueError, match="Falta correlación"):
        _service(contract).build(
            uncertainty_bound_action_candidate=_action_candidate(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            current_portfolio_value_base=5000.0,
            current_position_value_base=0.0,
            portfolio_valuation_evidence_fingerprint=VALUATION_FP,
            existing_position_instrument_ids=[20, 30],
            correlation_evidence=[_correlation(20)],
            as_of=AS_OF,
        )


def test_excessive_or_stale_correlation_blocks_increase():
    contract = _contract()
    for evidence, pattern in (
        (_correlation(correlation=0.90), "supera el límite"),
        (_correlation(last_date="2026-08-01"), "stale"),
    ):
        with pytest.raises(ValueError, match=pattern):
            _service(contract).build(
                uncertainty_bound_action_candidate=_action_candidate(),
                allocation_policy_id="allocation-001",
                economic_contract=contract,
                reference_capital=10000.0,
                base_currency="EUR",
                current_portfolio_value_base=5000.0,
                current_position_value_base=0.0,
                portfolio_valuation_evidence_fingerprint=VALUATION_FP,
                existing_position_instrument_ids=[20],
                correlation_evidence=[evidence],
                as_of=AS_OF,
            )


def test_flat_state_cannot_hide_existing_position_and_currency_must_match():
    contract = _contract()
    with pytest.raises(ValueError, match="flat"):
        _service(contract).build(
            uncertainty_bound_action_candidate=_action_candidate(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="EUR",
            current_portfolio_value_base=10000.0,
            current_position_value_base=1.0,
            portfolio_valuation_evidence_fingerprint=VALUATION_FP,
            existing_position_instrument_ids=[10],
            correlation_evidence=[],
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="moneda base"):
        _service(contract).build(
            uncertainty_bound_action_candidate=_action_candidate(),
            allocation_policy_id="allocation-001",
            economic_contract=contract,
            reference_capital=10000.0,
            base_currency="USD",
            current_portfolio_value_base=10000.0,
            current_position_value_base=0.0,
            portfolio_valuation_evidence_fingerprint=VALUATION_FP,
            existing_position_instrument_ids=[],
            correlation_evidence=[],
            as_of=AS_OF,
        )

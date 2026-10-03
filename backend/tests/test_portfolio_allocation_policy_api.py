from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import portfolio_allocation_policy as policy_api


POLICY = {
    "artifactVersion": "athena-allocation-policy-v1",
    "policyId": "user-policy-001",
    "baseCurrency": "EUR",
    "maximumInstrumentSleeveWeight": 0.10,
    "minimumCashReserveWeight": 0.20,
    "maximumAbsolutePairCorrelation": 0.75,
    "minimumCorrelationSampleCount": 30,
    "maximumCorrelationAgeSeconds": 86400,
    "semantics": {
        "referenceCapitalIsUserOwnedAllocationBase": True,
        "singleAssetExposureIsNotPortfolioWeight": True,
        "fullLongMeansFillInstrumentSleeveNotWholePortfolio": True,
        "reducedLongScalesInstrumentSleeveByFrozenEconomicContract": True,
        "sellTargetsZeroInstrumentWeight": True,
        "holdPreservesCurrentVerifiedWeight": True,
    },
    "policy": {
        "codeDefaultTargetWeight": False,
        "codeDefaultCorrelationThreshold": False,
        "codeDefaultStalenessThreshold": False,
        "automaticTrading": False,
    },
    "registeredAt": "2026-09-06T12:00:00+00:00",
    "policyFingerprint": "a" * 64,
}


def _record(policy=None):
    resolved = dict(POLICY if policy is None else policy)
    return {
        "id": 1,
        "policy_id": resolved["policyId"],
        "registered_at": resolved["registeredAt"],
        "policy": resolved,
        "policy_fingerprint": resolved["policyFingerprint"],
        "created_at": resolved["registeredAt"],
    }


class FakeRepository:
    records = [_record()]
    registered_payload = None

    def list_all(self):
        return list(self.records)

    def get(self, *, policy_id):
        for record in self.records:
            if record["policy_id"] == policy_id:
                return record
        return None

    def register(self, *, policy_draft):
        type(self).registered_payload = dict(policy_draft)
        return _record()

    def validate_record(self, record):
        return record


def test_list_requires_explicit_selection_and_exposes_no_default(monkeypatch):
    FakeRepository.records = [_record()]
    monkeypatch.setattr(policy_api, "RecommendationAllocationPolicyRepository", FakeRepository)

    result = policy_api.list_portfolio_allocation_policies()

    assert result["selection"] == {
        "explicitSelectionRequired": True,
        "policySelectionPerformed": False,
        "defaultPolicyExists": False,
        "automaticTrading": False,
    }
    assert result["data"][0]["policy"]["policyId"] == "user-policy-001"
    assert result["data"][0]["advisoryStatus"] == "no_advice"
    assert result["data"][0]["productionEligible"] is False
    assert result["data"][0]["allocationEligible"] is False
    assert result["data"][0]["automaticTrading"] is False
    assert result["data"][0]["policySelectionPerformed"] is False
    assert result["data"][0]["defaultPolicyExists"] is False


def test_register_forwards_exact_product_owned_limits_without_defaults(monkeypatch):
    FakeRepository.registered_payload = None
    monkeypatch.setattr(policy_api, "RecommendationAllocationPolicyRepository", FakeRepository)
    draft = {
        "artifactVersion": "athena-allocation-policy-v1",
        "policyId": "user-policy-001",
        "baseCurrency": "EUR",
        "maximumInstrumentSleeveWeight": 0.10,
        "minimumCashReserveWeight": 0.20,
        "maximumAbsolutePairCorrelation": 0.75,
        "minimumCorrelationSampleCount": 30,
        "maximumCorrelationAgeSeconds": 86400,
    }

    result = policy_api.post_portfolio_allocation_policy(draft)

    assert FakeRepository.registered_payload == draft
    assert "registeredAt" not in FakeRepository.registered_payload
    assert "policyFingerprint" not in FakeRepository.registered_payload
    assert result["data"]["defaultPolicyExists"] is False
    assert result["data"]["policySelectionPerformed"] is False


def test_get_missing_policy_fails_closed(monkeypatch):
    FakeRepository.records = []
    monkeypatch.setattr(policy_api, "RecommendationAllocationPolicyRepository", FakeRepository)

    with pytest.raises(HTTPException) as error:
        policy_api.get_portfolio_allocation_policy("missing")

    assert error.value.status_code == 404


def test_policy_that_enables_automatic_trading_is_rejected(monkeypatch):
    unsafe = dict(POLICY)
    unsafe["policy"] = dict(POLICY["policy"])
    unsafe["policy"]["automaticTrading"] = True
    FakeRepository.records = [_record(unsafe)]
    monkeypatch.setattr(policy_api, "RecommendationAllocationPolicyRepository", FakeRepository)

    with pytest.raises(HTTPException) as error:
        policy_api.list_portfolio_allocation_policies()

    assert error.value.status_code == 409
    assert "automaticTrading=False" in str(error.value.detail)

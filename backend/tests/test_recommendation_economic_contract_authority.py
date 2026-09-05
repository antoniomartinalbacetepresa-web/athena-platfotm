from __future__ import annotations

from copy import deepcopy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_economic_contract_authority import (
    RecommendationEconomicContractAuthority,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


def _contract():
    return RecommendationShadowActionEconomicContractService().build(
        transaction_cost_bps=5.0,
        slippage_bps=2.0,
        reduced_exposure_fraction=0.5,
        objective_name="mean_incremental_utility_vs_hold",
        objective_version="v1",
    )


def _authority(tmp_path):
    return RecommendationEconomicContractAuthority(
        AthenaDatabase(tmp_path / "athena.db")
    )


def test_seal_and_exact_fingerprint_roundtrip_are_idempotent(tmp_path):
    authority = _authority(tmp_path)
    contract = _contract()

    first = authority.seal(artifact=contract)
    second = authority.seal(artifact=contract)
    loaded = authority.get(
        economic_contract_fingerprint=contract["economicContractFingerprint"]
    )

    assert first == contract
    assert second == contract
    assert loaded == contract
    assert loaded["advisoryStatus"] == "no_advice"
    assert loaded["productionEligible"] is False
    assert loaded["constraints"]["automaticTrading"] is False


def test_unknown_or_invalid_fingerprint_fails_closed(tmp_path):
    authority = _authority(tmp_path)

    assert authority.get(economic_contract_fingerprint="a" * 64) is None
    with pytest.raises(ValueError, match="SHA-256"):
        authority.get(economic_contract_fingerprint="not-a-fingerprint")


def test_tampered_contract_cannot_be_sealed(tmp_path):
    authority = _authority(tmp_path)
    tampered = deepcopy(_contract())
    tampered["economicObjective"]["transactionCostBps"] = 999.0

    with pytest.raises(ValueError, match="fingerprint"):
        authority.seal(artifact=tampered)


def test_tampered_persisted_contract_is_rejected_on_read(tmp_path):
    authority = _authority(tmp_path)
    contract = _contract()
    authority.seal(artifact=contract)

    with authority._database.connect() as connection:
        tampered = deepcopy(contract)
        tampered["positionStates"]["reduced_long"]["targetExposureFraction"] = 0.9
        import json

        connection.execute(
            """
            UPDATE athena_recommendation_economic_contract_authority
            SET artifact_json = ?
            WHERE economic_contract_fingerprint = ?
            """,
            (json.dumps(tampered), contract["economicContractFingerprint"]),
        )

    with pytest.raises(ValueError):
        authority.get(
            economic_contract_fingerprint=contract["economicContractFingerprint"]
        )


def test_non_finite_contract_is_rejected_before_persistence(tmp_path):
    authority = _authority(tmp_path)
    contract = _contract()
    contract["economicObjective"]["transactionCostBps"] = float("nan")

    with pytest.raises(ValueError):
        authority.seal(artifact=contract)

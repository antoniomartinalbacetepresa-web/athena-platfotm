from __future__ import annotations

import math

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_allocation_policy_repository import (
    RecommendationAllocationPolicyRepository,
)


def _draft(**overrides):
    value = {
        "artifactVersion": "athena-allocation-policy-v1",
        "policyId": "allocation-001",
        "baseCurrency": "EUR",
        "maximumInstrumentSleeveWeight": 0.10,
        "minimumCashReserveWeight": 0.20,
        "maximumAbsolutePairCorrelation": 0.75,
        "minimumCorrelationSampleCount": 30,
        "maximumCorrelationAgeSeconds": 86400,
    }
    value.update(overrides)
    return value


def test_registry_generates_time_and_fingerprint_and_preserves_semantics(tmp_path):
    repository = RecommendationAllocationPolicyRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    record = repository.register(policy_draft=_draft())
    policy = record["policy"]

    assert policy["baseCurrency"] == "EUR"
    assert policy["maximumInstrumentSleeveWeight"] == 0.10
    assert policy["minimumCashReserveWeight"] == 0.20
    assert policy["semantics"]["singleAssetExposureIsNotPortfolioWeight"] is True
    assert policy["semantics"]["fullLongMeansFillInstrumentSleeveNotWholePortfolio"] is True
    assert policy["policy"]["codeDefaultTargetWeight"] is False
    assert policy["policy"]["automaticTrading"] is False
    assert len(policy["policyFingerprint"]) == 64
    assert "registeredAt" in policy
    assert repository.validate_record(record) is record


def test_registry_rejects_caller_backdating_or_fingerprint(tmp_path):
    repository = RecommendationAllocationPolicyRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    for field, value in (
        ("registeredAt", "2000-01-01T00:00:00+00:00"),
        ("policyFingerprint", "a" * 64),
    ):
        with pytest.raises(ValueError, match="los genera el registro"):
            repository.register(policy_draft=_draft(**{field: value}))


def test_policy_id_cannot_be_reused_with_different_limits(tmp_path):
    repository = RecommendationAllocationPolicyRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    repository.register(policy_draft=_draft())

    with pytest.raises(ValueError, match="inmutable"):
        repository.register(
            policy_draft=_draft(maximumInstrumentSleeveWeight=0.11)
        )


def test_sleeve_cannot_consume_required_cash_reserve(tmp_path):
    repository = RecommendationAllocationPolicyRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="reserva mínima"):
        repository.register(
            policy_draft=_draft(
                maximumInstrumentSleeveWeight=0.90,
                minimumCashReserveWeight=0.20,
            )
        )


def test_non_finite_or_implicit_limits_fail_closed(tmp_path):
    repository = RecommendationAllocationPolicyRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError):
        repository.register(
            policy_draft=_draft(maximumAbsolutePairCorrelation=math.nan)
        )
    incomplete = _draft()
    incomplete.pop("maximumCorrelationAgeSeconds")
    with pytest.raises(ValueError):
        repository.register(policy_draft=incomplete)


def test_persisted_payload_tampering_is_detected(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationAllocationPolicyRepository(database)
    record = repository.register(policy_draft=_draft())

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_allocation_policies
            SET policy_json = replace(policy_json, '0.1', '0.2')
            WHERE policy_id = ?
            """,
            (record["policy_id"],),
        )

    with pytest.raises(ValueError):
        repository.get(policy_id=record["policy_id"])

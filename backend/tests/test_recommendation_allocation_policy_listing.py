from __future__ import annotations

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_allocation_policy_repository import (
    RecommendationAllocationPolicyRepository,
)


def _draft(policy_id: str, sleeve: float) -> dict[str, object]:
    return {
        "artifactVersion": "athena-allocation-policy-v1",
        "policyId": policy_id,
        "baseCurrency": "EUR",
        "maximumInstrumentSleeveWeight": sleeve,
        "minimumCashReserveWeight": 0.20,
        "maximumAbsolutePairCorrelation": 0.75,
        "minimumCorrelationSampleCount": 30,
        "maximumCorrelationAgeSeconds": 86400,
    }


def test_list_all_returns_only_revalidated_persisted_policies(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationAllocationPolicyRepository(database)
    first = repository.register(policy_draft=_draft("policy-a", 0.10))
    second = repository.register(policy_draft=_draft("policy-b", 0.15))

    listed = RecommendationAllocationPolicyRepository(database).list_all()

    assert [record["policy_id"] for record in listed] == ["policy-a", "policy-b"]
    assert listed[0]["policy"] == first["policy"]
    assert listed[1]["policy"] == second["policy"]
    assert all(record["policy"]["policy"]["automaticTrading"] is False for record in listed)


def test_list_all_fails_closed_when_any_persisted_policy_is_tampered(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationAllocationPolicyRepository(database)
    repository.register(policy_draft=_draft("policy-a", 0.10))

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_allocation_policies
            SET policy_json = replace(policy_json, '0.1', '0.2')
            WHERE policy_id = 'policy-a'
            """
        )

    with pytest.raises(ValueError):
        RecommendationAllocationPolicyRepository(database).list_all()

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.longitudinal_oos_policy_repository import (
    LongitudinalOosPolicyRepository,
)
from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)


CRITERIA = {
    "minimumEvaluationSpanDays": 180,
    "minimumDistinctEvaluationPeriods": 6,
    "minimumEligibleOutcomes": 100,
    "minimumDistinctResolvedIssuers": 20,
    "requiredHorizonSeconds": [86400, 604800],
    "dependencyHandling": "issuer_clustered_period_aware_review",
}


def _repository(tmp_path) -> LongitudinalOosPolicyRepository:
    return LongitudinalOosPolicyRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def test_persists_policy_and_human_approval_bound_to_exact_fingerprint(tmp_path) -> None:
    repository = _repository(tmp_path)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="governance-review-2026-09",
    )
    fingerprint = policy["artifact"]["policyFingerprint"]

    assert fingerprint == LongitudinalOosSufficiencyPolicyService.fingerprint(
        policy_id="longitudinal-oos-v1", version=1, criteria=CRITERIA
    )
    assert policy["artifact"]["automaticApproval"] is False
    assert policy["artifact"]["automaticProductionPromotion"] is False

    approval = repository.approve_policy(
        policy_fingerprint=fingerprint,
        approved_by="human-reviewer-1",
        evidence_ref="signed-policy-review-2026-09",
        human_review_confirmed=True,
    )
    assert approval["artifact"]["humanReviewConfirmed"] is True
    assert approval["artifact"]["approvalMode"] == "offline_human_operator"
    assert approval["artifact"]["automaticApproval"] is False
    assert repository.get_latest_policy() == policy
    assert repository.get_latest_approval(policy_fingerprint=fingerprint) == approval


def test_rejects_approval_without_explicit_human_confirmation(tmp_path) -> None:
    repository = _repository(tmp_path)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )

    with pytest.raises(ValueError, match="human_review_confirmed"):
        repository.approve_policy(
            policy_fingerprint=policy["artifact"]["policyFingerprint"],
            approved_by="reviewer",
            evidence_ref="review",
            human_review_confirmed=False,
        )


def test_approval_requires_policy_visible_at_approval_time(tmp_path) -> None:
    repository = _repository(tmp_path)
    now = datetime.now(timezone.utc)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="policy-review",
        precommitted_at=now,
    )

    with pytest.raises(ValueError, match="visible"):
        repository.approve_policy(
            policy_fingerprint=policy["artifact"]["policyFingerprint"],
            approved_by="reviewer",
            evidence_ref="review",
            human_review_confirmed=True,
            approved_at=now - timedelta(seconds=1),
        )


def test_policy_and_approval_lookups_are_point_in_time(tmp_path) -> None:
    repository = _repository(tmp_path)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )
    fingerprint = policy["artifact"]["policyFingerprint"]
    precommitted_at = datetime.fromisoformat(
        policy["artifact"]["precommittedAt"].replace("Z", "+00:00")
    )

    assert repository.get_latest_policy(
        as_of=precommitted_at - timedelta(microseconds=1)
    ) is None
    approval = repository.approve_policy(
        policy_fingerprint=fingerprint,
        approved_by="reviewer",
        evidence_ref="review",
        human_review_confirmed=True,
    )
    approved_at = datetime.fromisoformat(
        approval["artifact"]["approvedAt"].replace("Z", "+00:00")
    )
    assert repository.get_latest_approval(
        policy_fingerprint=fingerprint,
        as_of=approved_at - timedelta(microseconds=1),
    ) is None


def test_policy_change_produces_new_fingerprint_and_old_approval_does_not_transfer(tmp_path) -> None:
    repository = _repository(tmp_path)
    first = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="policy-review-v1",
    )
    repository.approve_policy(
        policy_fingerprint=first["artifact"]["policyFingerprint"],
        approved_by="reviewer",
        evidence_ref="approval-v1",
        human_review_confirmed=True,
    )
    stricter = dict(CRITERIA)
    stricter["minimumEligibleOutcomes"] = 120
    second = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=2,
        criteria=stricter,
        precommitted_by="research-governance",
        evidence_ref="policy-review-v2",
    )

    assert second["artifact"]["policyFingerprint"] != first["artifact"]["policyFingerprint"]
    assert repository.get_latest_approval(
        policy_fingerprint=second["artifact"]["policyFingerprint"]
    ) is None


def test_detects_tampering_of_persisted_policy_artifact(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = LongitudinalOosPolicyRepository(database=database)
    policy = repository.register_policy(
        policy_id="longitudinal-oos-v1",
        version=1,
        criteria=CRITERIA,
        precommitted_by="research-governance",
        evidence_ref="policy-review",
    )

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_longitudinal_oos_policies
            SET artifact_json = replace(artifact_json, '100', '101')
            WHERE policy_fingerprint = ?
            """,
            (policy["artifact"]["policyFingerprint"],),
        )

    with pytest.raises(RuntimeError, match="alterado"):
        repository.get_latest_policy()

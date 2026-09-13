from datetime import datetime, timezone

from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)


def _criteria() -> dict[str, object]:
    # Test-only values exercise governance mechanics; they are not production policy.
    return {
        "minimumEvaluationSpanDays": 30,
        "minimumDistinctEvaluationPeriods": 3,
        "minimumEligibleOutcomes": 10,
        "minimumDistinctResolvedIssuers": 4,
        "requiredHorizonSeconds": [604800, 2592000],
        "dependencyHandling": "issuer_clustered_test_only",
    }


def _policy(criteria: dict[str, object] | None = None) -> dict[str, object]:
    selected = criteria or _criteria()
    fingerprint = LongitudinalOosSufficiencyPolicyService.fingerprint(
        policy_id="test-policy", version=1, criteria=selected
    )
    return {
        "artifact": {
            "module": "longitudinal_oos_sufficiency_policy",
            "policyId": "test-policy",
            "version": 1,
            "criteria": selected,
            "policyFingerprint": fingerprint,
        }
    }


def _approval(fingerprint: str) -> dict[str, object]:
    return {
        "artifact": {
            "status": "approved",
            "policyFingerprint": fingerprint,
            "approvedBy": "test-human-reviewer",
            "approvedAt": "2026-01-01T00:00:00+00:00",
            "evidenceRef": "test-evidence-only",
        }
    }


def _measurement() -> dict[str, object]:
    return {
        "evaluationSpanDays": 40.0,
        "distinctEvaluationPeriodCount": 4,
        "eligibleOutcomeCount": 12,
        "distinctResolvedIssuerCount": 5,
        "horizons": {"604800": {}, "2592000": {}},
    }


def test_no_policy_or_approval_cannot_claim_sufficiency() -> None:
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=None,
        approval_record=None,
    )
    assert result["status"] == "policy_not_precommitted"
    assert result["policyApproved"] is False
    assert result["acceptanceEvidenceVerified"] is False
    assert result["productionSufficiencyClaimed"] is False


def test_precommitted_policy_stays_blocked_without_human_approval() -> None:
    policy = _policy()
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=policy,
        approval_record=None,
    )
    assert result["status"] == "policy_approval_required"
    assert result["policyApproved"] is False


def test_policy_mutation_invalidates_previous_approval() -> None:
    original = _policy()
    old_fingerprint = original["artifact"]["policyFingerprint"]
    criteria = _criteria()
    criteria["minimumEligibleOutcomes"] = 11
    mutated = _policy(criteria)

    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=mutated,
        approval_record=_approval(str(old_fingerprint)),
    )
    assert result["status"] == "policy_approval_stale"
    assert result["policyApproved"] is False
    assert result["acceptanceEvidenceVerified"] is False


def test_valid_approval_is_still_separate_from_evidence_satisfaction() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])
    weak = _measurement()
    weak["distinctEvaluationPeriodCount"] = 2

    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        measurement=weak,
        policy_record=policy,
        approval_record=_approval(fingerprint),
    )
    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["policyApproved"] is True
    assert result["acceptanceEvidenceVerified"] is False
    assert result["productionSufficiencyClaimed"] is False


def test_test_only_policy_can_prove_mechanics_without_production_claim() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 2, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=policy,
        approval_record=_approval(fingerprint),
    )
    assert result["status"] == "precommitted_policy_satisfied"
    assert result["policyApproved"] is True
    assert result["acceptanceEvidenceVerified"] is True
    assert result["productionSufficiencyClaimed"] is False
    assert result["automaticApproval"] is False
    assert result["automaticProductionPromotion"] is False

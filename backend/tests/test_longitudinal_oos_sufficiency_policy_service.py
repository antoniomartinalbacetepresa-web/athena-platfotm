from datetime import datetime, timezone
import pytest

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


def _approval(fingerprint: str, *, approved_at: str = "2026-01-01T00:00:00+00:00") -> dict[str, object]:
    return {
        "artifact": {
            "status": "approved",
            "policyFingerprint": fingerprint,
            "approvedBy": "test-human-reviewer",
            "approvedAt": approved_at,
            "evidenceRef": "test-evidence-only",
        }
    }


def _measurement() -> dict[str, object]:
    return {
        "evaluationSpanDays": 40.0,
        "distinctEvaluationPeriodCount": 4,
        "eligibleOutcomeCount": 12,
        "forecastErrorCount": 12,
        "distinctResolvedIssuerCount": 5,
        "firstEvaluationPeriodStart": "2026-01-01T12:00:00+00:00",
        "firstEvaluationPeriodEnd": "2026-01-02T00:00:00+00:00",
        "lastEvaluationPeriodEnd": "2026-02-11T00:00:00+00:00",
        "horizons": {
            "604800": {"forecastErrorCount": 6},
            "2592000": {"forecastErrorCount": 6},
        },
    }


@pytest.mark.parametrize("start", [None, "2025-12-31T00:00:00+00:00", "2026-01-01T00:00:00+00:00"])
def test_approval_before_end_is_not_precommitment_without_an_earlier_period_start(start):
    policy = _policy()
    measurement = _measurement()
    measurement["firstEvaluationPeriodStart"] = start
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=measurement, policy_record=policy,
        approval_record=_approval(str(policy["artifact"]["policyFingerprint"])),
    )
    assert result["policyApproved"] is True
    assert result["temporalPrecommitmentVerified"] is False
    assert result["acceptanceEvidenceVerified"] is False


def test_period_start_without_timezone_cannot_prove_precommitment():
    policy = _policy()
    measurement = _measurement()
    measurement["firstEvaluationPeriodStart"] = "2026-01-01T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        LongitudinalOosSufficiencyPolicyService().evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            measurement=measurement, policy_record=policy,
            approval_record=_approval(str(policy["artifact"]["policyFingerprint"])),
        )


def test_no_policy_or_approval_cannot_claim_sufficiency() -> None:
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=None,
        approval_record=None,
    )
    assert result["status"] == "policy_not_precommitted"
    assert result["policyApproved"] is False
    assert result["acceptanceEvidenceVerified"] is False
    assert result["temporalPrecommitmentVerified"] is False
    assert result["productionSufficiencyClaimed"] is False


def test_precommitted_policy_stays_blocked_without_human_approval() -> None:
    policy = _policy()
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
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
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
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
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=weak,
        policy_record=policy,
        approval_record=_approval(fingerprint),
    )
    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["policyApproved"] is True
    assert result["acceptanceEvidenceVerified"] is False
    assert result["temporalPrecommitmentVerified"] is True
    assert result["productionSufficiencyClaimed"] is False


def test_human_approval_after_observed_oos_evidence_cannot_bless_history() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])

    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=policy,
        approval_record=_approval(
            fingerprint, approved_at="2026-02-20T00:00:00+00:00"
        ),
    )

    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["policyApproved"] is True
    assert result["temporalPrecommitmentVerified"] is False
    assert result["acceptanceEvidenceVerified"] is False
    assert result["satisfiedCriteriaCount"] == result["criteriaCheckCount"] - 1


def test_same_instant_approval_and_first_evidence_fails_closed() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])

    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=policy,
        approval_record=_approval(
            fingerprint, approved_at="2026-01-02T00:00:00+00:00"
        ),
    )

    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["temporalPrecommitmentVerified"] is False
    assert result["acceptanceEvidenceVerified"] is False


def test_future_dated_measurement_cannot_satisfy_policy_as_of_cutoff() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])
    measurement = _measurement()
    measurement["lastEvaluationPeriodEnd"] = "2026-04-01T00:00:00+00:00"

    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=measurement,
        policy_record=policy,
        approval_record=_approval(fingerprint),
    )

    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["temporalPrecommitmentVerified"] is False
    assert result["acceptanceEvidenceVerified"] is False


def test_test_only_policy_can_prove_mechanics_without_production_claim() -> None:
    policy = _policy()
    fingerprint = str(policy["artifact"]["policyFingerprint"])
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
        measurement=_measurement(),
        policy_record=policy,
        approval_record=_approval(fingerprint),
    )
    assert result["status"] == "precommitted_policy_satisfied"
    assert result["policyApproved"] is True
    assert result["temporalPrecommitmentVerified"] is True
    assert result["acceptanceEvidenceVerified"] is True
    assert result["productionSufficiencyClaimed"] is False
    assert result["automaticApproval"] is False
    assert result["automaticProductionPromotion"] is False


def test_eligible_outcomes_do_not_substitute_for_measured_forecast_errors() -> None:
    policy = _policy()
    measurement = _measurement()
    measurement["forecastErrorCount"] = 9
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc), measurement=measurement,
        policy_record=policy,
        approval_record=_approval(str(policy["artifact"]["policyFingerprint"])),
    )
    assert result["status"] == "precommitted_policy_not_satisfied"
    assert result["acceptanceEvidenceVerified"] is False


def test_required_horizon_without_measured_errors_cannot_satisfy_policy() -> None:
    policy = _policy()
    measurement = _measurement()
    measurement["horizons"]["2592000"] = {"forecastErrorCount": 0}
    result = LongitudinalOosSufficiencyPolicyService().evaluate(
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc), measurement=measurement,
        policy_record=policy,
        approval_record=_approval(str(policy["artifact"]["policyFingerprint"])),
    )
    assert result["policyApproved"] is True
    assert result["acceptanceEvidenceVerified"] is False
    assert result["productionSufficiencyClaimed"] is False

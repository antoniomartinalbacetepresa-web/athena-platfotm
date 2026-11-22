"""Release gate regression matrix; does not claim deployed acceptance."""

import pytest

from scripts.release_validation_gate import ReleaseGateFailure, check_release_gate


def config(**overrides):
    values = {
        "BACKEND_RESULT": "success", "FLUTTER_RESULT": "success",
        "DEPLOYED_RESULT": "skipped", "BROWSER_RESULT": "skipped",
        "DEPLOYED_ENABLED": "", "BROWSER_ENABLED": "",
        "OWNER_BROWSER_ENABLED": "", "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/dev/real-market-backend",
        "GITHUB_BASE_REF": "",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("field", ["BACKEND_RESULT", "FLUTTER_RESULT"])
def test_core_failures_block_even_with_deployed_jobs_disabled(field):
    with pytest.raises(ReleaseGateFailure):
        check_release_gate(config(**{field: "failure"}))


@pytest.mark.parametrize("field", [
    "DEPLOYED_ENABLED", "BROWSER_ENABLED", "OWNER_BROWSER_ENABLED",
])
def test_malformed_opt_in_flags_fail_closed(field):
    with pytest.raises(ReleaseGateFailure, match="Invalid"):
        check_release_gate(config(**{field: "tru"}))


def test_unconfigured_deployment_does_not_claim_staging():
    check_release_gate(config())


@pytest.mark.parametrize("field,result", [
    ("DEPLOYED_RESULT", "failure"), ("DEPLOYED_RESULT", "skipped"),
    ("BROWSER_RESULT", "failure"), ("BROWSER_RESULT", "skipped"),
])
def test_enabled_deployed_gate_must_succeed(field, result):
    enabled = "DEPLOYED_ENABLED" if field == "DEPLOYED_RESULT" else "BROWSER_ENABLED"
    with pytest.raises(ReleaseGateFailure):
        check_release_gate(config(**{enabled: "true", field: result}))


def test_independent_guest_or_api_gate_can_run_alone():
    check_release_gate(config(BROWSER_ENABLED="true", BROWSER_RESULT="success"))
    check_release_gate(config(DEPLOYED_ENABLED="true", DEPLOYED_RESULT="success"))


@pytest.mark.parametrize("deployed,browser", [
    ("", ""), ("true", ""), ("", "true"),
])
def test_owner_browser_requires_both_independent_deployed_gates(deployed, browser):
    with pytest.raises(ReleaseGateFailure, match="requires deployed API"):
        check_release_gate(config(
            OWNER_BROWSER_ENABLED="true", DEPLOYED_ENABLED=deployed,
            BROWSER_ENABLED=browser,
            DEPLOYED_RESULT="success", BROWSER_RESULT="success",
        ))


def test_owner_browser_requires_both_actual_successes():
    check_release_gate(config(
        OWNER_BROWSER_ENABLED="true", DEPLOYED_ENABLED="true",
        BROWSER_ENABLED="true", DEPLOYED_RESULT="success",
        BROWSER_RESULT="success",
    ))
    with pytest.raises(ReleaseGateFailure):
        check_release_gate(config(
            OWNER_BROWSER_ENABLED="true", DEPLOYED_ENABLED="true",
            BROWSER_ENABLED="true", DEPLOYED_RESULT="skipped",
            BROWSER_RESULT="success",
        ))


def test_pr_green_is_not_deployed_evidence_and_wrong_push_branch_fails():
    check_release_gate(config(
        GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/1/merge",
        GITHUB_BASE_REF="dev/real-market-backend",
        DEPLOYED_ENABLED="true", BROWSER_ENABLED="true",
    ))
    with pytest.raises(ReleaseGateFailure, match="authorized development branch"):
        check_release_gate(config(GITHUB_REF="refs/heads/main"))


def test_unsupported_event_fails_closed():
    with pytest.raises(ReleaseGateFailure):
        check_release_gate(config(GITHUB_EVENT_NAME="schedule"))


@pytest.mark.parametrize("base_ref", ["", "main", "dev/other-branch"])
def test_pr_release_gate_rejects_missing_or_unauthorized_target(base_ref):
    with pytest.raises(ReleaseGateFailure, match="authorized PR target branch"):
        check_release_gate(config(
            GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/42/merge",
            GITHUB_BASE_REF=base_ref,
        ))


def test_pr_release_gate_accepts_authorized_target_without_claiming_deployment():
    check_release_gate(config(
        GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/42/merge",
        GITHUB_BASE_REF="dev/real-market-backend",
        DEPLOYED_ENABLED="true", BROWSER_ENABLED="true",
        DEPLOYED_RESULT="skipped", BROWSER_RESULT="skipped",
    ))


@pytest.mark.parametrize("ref", [
    "", "refs/heads/dev/real-market-backend", "refs/pull/0/merge",
    "refs/pull/-1/merge", "refs/pull/42/head", "refs/pull/42/merge/extra",
])
def test_pr_release_gate_rejects_non_merge_or_malformed_refs(ref):
    with pytest.raises(ReleaseGateFailure, match="pull request merge ref"):
        check_release_gate(config(
            GITHUB_EVENT_NAME="pull_request", GITHUB_REF=ref,
            GITHUB_BASE_REF="dev/real-market-backend",
        ))


def test_pr_release_gate_accepts_valid_numbered_merge_ref():
    check_release_gate(config(
        GITHUB_EVENT_NAME="pull_request",
        GITHUB_REF="refs/pull/123/merge",
        GITHUB_BASE_REF="dev/real-market-backend",
    ))

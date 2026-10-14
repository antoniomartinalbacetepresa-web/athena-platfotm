from __future__ import annotations

from scripts.canonical_weighting_governance import exit_code_for_result


def test_current_command_returns_success_only_for_fresh_human_approval() -> None:
    assert exit_code_for_result(
        "current",
        {"status": "human_approved", "humanApproved": True},
    ) == 0

    assert exit_code_for_result(
        "current",
        {"status": "blocked_pending_human_approval", "humanApproved": False},
    ) != 0
    assert exit_code_for_result(
        "current",
        {
            "status": "blocked_stale_evidence_requires_human_approval",
            "humanApproved": True,
            "evidenceFresh": False,
        },
    ) != 0


def test_current_command_fails_closed_for_unknown_or_missing_status() -> None:
    assert exit_code_for_result("current", {"status": "unexpected"}) != 0
    assert exit_code_for_result("current", {}) != 0


def test_non_current_governance_actions_are_not_readiness_assertions() -> None:
    assert exit_code_for_result("propose", {"status": "pending_human_approval"}) == 0
    assert exit_code_for_result("approve", {"status": "approved"}) == 0
    assert exit_code_for_result("reject", {"status": "rejected"}) == 0
    assert exit_code_for_result("show", {"status": "approved"}) == 0

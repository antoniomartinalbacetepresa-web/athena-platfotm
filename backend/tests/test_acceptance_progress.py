"""Acceptance-progress accounting must fail closed, including in CI."""
import copy
import json

import pytest

from scripts.acceptance_progress import INVENTORY, summarize, validate


@pytest.fixture
def inventory():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_baseline_cannot_certify_historical_91_or_85(inventory):
    result = summarize(inventory)
    for scope in ("core", "product"):
        assert result["scopes"][scope]["percent"] is None
        assert result["scopes"][scope]["certifiable"] is False
        assert result["scopes"][scope]["complete"] is False
        # A living audit must allow individual reviewed criteria while
        # refusing to certify an incomplete scope or mapping.
        assert result["scopes"][scope]["reviewed"] == sum(
            r["reviewed"] for r in inventory["criteria"] if scope in r["scopes"]
        )
        assert result["scopes"][scope]["reviewed"] < result["scopes"][scope]["criteria"]
        assert result["scopes"][scope]["mappingReviewed"] is False


def test_scope_counts_do_not_duplicate_criteria(inventory):
    result = summarize(inventory)
    assert result["scopes"]["core"]["criteria"] == sum("core" in r["scopes"] for r in inventory["criteria"])
    assert result["scopes"]["product"]["criteria"] == len(inventory["criteria"])


@pytest.mark.parametrize("field,value", [
    ("weight", 0), ("weight", True), ("requiredLevel", "production"),
    ("status", "verified_by_fixture"), ("reviewed", "yes"),
])
def test_invalid_criterion_rejected(inventory, field, value):
    inventory["criteria"][0][field] = value
    with pytest.raises(ValueError):
        validate(inventory)


def test_duplicate_ids_rejected(inventory):
    inventory["criteria"][1]["id"] = inventory["criteria"][0]["id"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate(inventory)


def test_implemented_without_ci_evidence_rejected(inventory):
    inventory["criteria"][0]["evidence"] = []
    with pytest.raises(ValueError, match="evidence"):
        validate(inventory)


def test_real_data_cannot_be_promoted_with_ci_only(inventory):
    inventory["criteria"][0]["status"] = "real_data"
    with pytest.raises(ValueError, match="operational evidence"):
        validate(inventory)


def test_unreviewed_mapping_blocks_percent_even_with_reviewed_rows(inventory):
    for row in inventory["criteria"]:
        row["reviewed"] = True
    result = summarize(inventory)
    assert result["scopes"]["core"]["percent"] is None


def test_mapping_and_row_review_allow_transparent_partial_score(inventory):
    for row in inventory["criteria"]:
        row["reviewed"] = True
    inventory["scopeMappingReviewed"] = {"core": True, "product": True}
    result = summarize(inventory)
    for scope in ("core", "product"):
        assert result["scopes"][scope]["certifiable"] is True
        assert 0 < result["scopes"][scope]["percent"] < 100
        assert result["scopes"][scope]["complete"] is False


def test_all_complete_requires_gates(inventory):
    for row in inventory["criteria"]:
        row["reviewed"] = True
        row["status"] = row["requiredLevel"]
        row["evidence"].append({
            "kind": "deployment" if row["requiredLevel"] == "deployed" else "real_data" if row["requiredLevel"] == "real_data" else "ci",
            "sha": inventory["baselineCommit"],
            "url": "https://github.com/example/repo/actions/runs/1",
            "path": "test" if row["requiredLevel"] == "implemented_ci" else "",
        })
    inventory["scopeMappingReviewed"] = {"core": True, "product": True}
    result = summarize(inventory)
    assert result["scopes"]["product"]["percent"] == 100
    assert result["scopes"]["product"]["complete"] is False
    for gate in inventory["mandatoryGates"]:
        gate["verified"] = True
        gate["evidence"] = "https://github.com/example/repo/actions/runs/1"
    assert summarize(inventory)["scopes"]["product"]["complete"] is True

"""Independent, offline verification of transferred paired diagnostic evidence."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import verify_operational_history_bundle as verifier

CUTOFF = "2026-10-01T12:00:00+00:00"
SNAPSHOT_SHA = "b" * 64
SOURCE_SHA = SNAPSHOT_SHA


def _bundle(tmp_path: Path, *, change=None, extra_member=False):
    history_meta = {
        "recordType": "metadata", "status": "complete_pit_history_diagnostic",
        "asOf": CUTOFF, "snapshotSha256": SNAPSHOT_SHA,
        "eligibleInstrumentCount": 2, "currentDeepHistoryInstrumentCount": 1,
        "totalBlockingCount": 1,
        "blockingByReason": {reason: int(reason == "no_observations") for reason in verifier.REASONS},
        "completeExport": True, "productionCoverageClaimed": False,
    }
    action_meta = {
        "recordType": "metadata", "status": "complete_pit_reconciliation_diagnostic",
        "asOf": CUTOFF, "snapshotSha256": SNAPSHOT_SHA,
        "totalUnresolvedEventCount": 1, "totalIncompleteEventCount": 1,
        "totalConflictEventCount": 0, "completeExport": True,
        "productionCoverageClaimed": False,
    }
    rows = {
        verifier.HISTORY: [history_meta, {
            "recordType": "history_gap", "instrumentId": 1,
            "symbol": "A", "reason": "no_observations",
        }],
        verifier.ACTIONS: [action_meta, {
            "instrumentId": 1, "symbol": "A", "actionType": "dividend",
            "effectiveAt": "2026-09-01T00:00:00+00:00",
            "reconciliationStatus": "incomplete", "automaticCanonicalization": False,
            "requiredIndependentFamilyCount": 2,
        }],
    }
    manifest = {
        "artifactVersion": "athena-paired-operational-evidence-v1",
        "asOf": CUTOFF, "status": "diagnostic_only",
        "sourceGenerationSha256": SOURCE_SHA, "sameSourceGeneration": True,
        "operationalOriginVerified": False, "independentProviderAgreementVerified": False,
        "productionCoverageClaimed": False, "automaticBackfill": False,
        "automaticCanonicalization": False, "productionLearningEligible": False,
        "automaticTrading": False,
    }
    if change:
        change(rows, manifest)
    contents = {name: b"".join(json.dumps(row, sort_keys=True).encode() + b"\n"
                               for row in entries) for name, entries in rows.items()}
    summaries = {}
    for name, entries in rows.items():
        meta = entries[0]
        keys = (("eligibleInstrumentCount", "currentDeepHistoryInstrumentCount", "totalBlockingCount")
                if name == verifier.HISTORY else
                ("totalUnresolvedEventCount", "totalIncompleteEventCount", "totalConflictEventCount"))
        summaries[name] = {key: meta[key] for key in keys}
        summaries[name].update({"asOf": CUTOFF, "snapshotSha256": meta["snapshotSha256"],
                                "productionCoverageClaimed": False,
                                "exportSha256": hashlib.sha256(contents[name]).hexdigest()})
    manifest.update({"history": summaries[verifier.HISTORY],
                     "corporateActions": summaries[verifier.ACTIONS],
                     "members": {name: hashlib.sha256(data).hexdigest()
                                 for name, data in contents.items()}})
    path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        archive.writestr(verifier.MANIFEST, json.dumps(manifest))
        if extra_member:
            archive.writestr("../untrusted.txt", "unexpected")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_offline_verifier_accepts_complete_paired_evidence_without_claiming_origin(tmp_path):
    path, sha = _bundle(tmp_path)
    result = verifier.verify_bundle(path, expected_sha256=sha)
    assert result["custodySha256Matched"] is True
    assert result["historyBlockingCount"] == 1
    assert result["corporateActionUnresolvedCount"] == 1
    assert result["operationalOriginVerified"] is False
    assert result["productionAuthorization"] is False


def test_requires_independent_custody_digest(tmp_path):
    path, sha = _bundle(tmp_path)
    with pytest.raises(ValueError, match="custody"):
        verifier.verify_bundle(path, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="independently"):
        verifier.verify_bundle(path, expected_sha256="not-a-sha")
    assert verifier.verify_bundle(path, expected_sha256=sha)["status"] == "paired_diagnostic_bundle_verified"


def test_rejects_rehashed_missing_history_row(tmp_path):
    path, sha = _bundle(tmp_path, change=lambda rows, manifest: rows[verifier.HISTORY].pop())
    with pytest.raises(ValueError, match="totals"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_rehashed_authority_escalation(tmp_path):
    def escalate(rows, manifest):
        manifest["productionCoverageClaimed"] = True
    path, sha = _bundle(tmp_path, change=escalate)
    with pytest.raises(ValueError, match="authority"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_duplicate_instrument_even_if_rehashed(tmp_path):
    def duplicate(rows, manifest):
        rows[verifier.HISTORY].append(dict(rows[verifier.HISTORY][1]))
        rows[verifier.HISTORY][0]["totalBlockingCount"] = 2
        rows[verifier.HISTORY][0]["eligibleInstrumentCount"] = 3
        rows[verifier.HISTORY][0]["blockingByReason"]["no_observations"] = 2
    path, sha = _bundle(tmp_path, change=duplicate)
    with pytest.raises(ValueError, match="Duplicate history instrument"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_unexpected_zip_member(tmp_path):
    path, sha = _bundle(tmp_path, extra_member=True)
    with pytest.raises(ValueError, match="ZIP members"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_inconsistent_rehashed_action_status(tmp_path):
    def mismatch(rows, manifest):
        rows[verifier.ACTIONS][1]["reconciliationStatus"] = "conflict"
    path, sha = _bundle(tmp_path, change=mismatch)
    with pytest.raises(ValueError, match="totals"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_mixed_generations_with_rehashed_child_and_custody_digest(tmp_path):
    def mix(rows, manifest):
        rows[verifier.ACTIONS][0]["snapshotSha256"] = "c" * 64
    path, sha = _bundle(tmp_path, change=mix)
    with pytest.raises(ValueError, match="source generations"):
        verifier.verify_bundle(path, expected_sha256=sha)


def test_rejects_forged_source_generation_even_if_children_match(tmp_path):
    def forge(rows, manifest):
        manifest["sourceGenerationSha256"] = "a" * 64
    path, sha = _bundle(tmp_path, change=forge)
    with pytest.raises(ValueError, match="source generations"):
        verifier.verify_bundle(path, expected_sha256=sha)

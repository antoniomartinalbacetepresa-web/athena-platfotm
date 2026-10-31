"""Independently verify a transferred paired PIT diagnostic ZIP against a custody SHA.

No database access, network requests, backfill, canonicalization or production approval.
The SHA must come from an independently retained operator record, not the ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HISTORY = "market_history_gaps.jsonl"
ACTIONS = "corporate_action_reconciliation.jsonl"
MANIFEST = "manifest.json"
MEMBERS = {HISTORY, ACTIONS, MANIFEST}
REASONS = ("no_observations", "insufficient_span", "discontinuous_source", "stale_source")
MAX_ROW_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _json(raw: bytes):
    return json.loads(raw, object_pairs_hook=_unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON constant")))


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _verify_report(archive: zipfile.ZipFile, member: str, summary: dict,
                   *, cutoff: str, expected_digest: str) -> dict:
    if not isinstance(summary, dict) or not _is_sha(expected_digest):
        raise ValueError("Invalid child report summary")
    is_history = member == HISTORY
    fields = (("eligibleInstrumentCount", "currentDeepHistoryInstrumentCount", "totalBlockingCount")
              if is_history else ("totalUnresolvedEventCount", "totalIncompleteEventCount", "totalConflictEventCount"))
    categories = REASONS if is_history else ("incomplete", "conflict")
    total_field = "totalBlockingCount" if is_history else "totalUnresolvedEventCount"
    counts = dict.fromkeys(categories, 0)
    digest = hashlib.sha256()
    previous = None
    seen_ids: set[int] = set()
    metadata = None
    with archive.open(member) as stream:
        for index, raw in enumerate(iter(lambda: stream.readline(MAX_ROW_BYTES + 1), b"")):
            if len(raw) > MAX_ROW_BYTES or not raw.endswith(b"\n"):
                raise ValueError("Invalid or oversized JSONL record")
            digest.update(raw)
            row = _json(raw)
            if not isinstance(row, dict):
                raise ValueError("Non-object JSONL record")
            if index == 0:
                metadata = row
                status = ("complete_pit_history_diagnostic" if is_history
                          else "complete_pit_reconciliation_diagnostic")
                if (row.get("recordType") != "metadata" or row.get("status") != status
                    or row.get("asOf") != cutoff or row.get("completeExport") is not True
                    or row.get("productionCoverageClaimed") is not False
                    or not _is_sha(row.get("snapshotSha256"))
                    or any(not _nonnegative_int(row.get(f)) or row[f] != summary.get(f)
                           for f in fields)):
                    raise ValueError("Child report metadata mismatch")
                if is_history:
                    by_reason = row.get("blockingByReason")
                    if (not isinstance(by_reason, dict) or set(by_reason) != set(REASONS)
                        or any(not _nonnegative_int(v) for v in by_reason.values())
                        or sum(by_reason.values()) != row[total_field]):
                        raise ValueError("History category totals mismatch")
                continue
            instrument_id, symbol = row.get("instrumentId"), row.get("symbol")
            if (type(instrument_id) is not int or instrument_id <= 0
                or not isinstance(symbol, str) or not symbol):
                raise ValueError("Invalid instrument identity")
            if is_history:
                category = row.get("reason")
                if row.get("recordType") != "history_gap" or category not in counts:
                    raise ValueError("Invalid history row")
                key = (REASONS.index(category), symbol, instrument_id)
                if instrument_id in seen_ids:
                    raise ValueError("Duplicate history instrument")
                seen_ids.add(instrument_id)
            else:
                category = row.get("reconciliationStatus")
                action, effective = row.get("actionType"), row.get("effectiveAt")
                if (category not in counts or action not in ("dividend", "split")
                    or not isinstance(effective, str) or not effective
                    or row.get("automaticCanonicalization") is not False
                    or row.get("requiredIndependentFamilyCount") != 2):
                    raise ValueError("Invalid corporate-action row")
                key = (instrument_id, action, effective)
            if previous is not None and key <= previous:
                raise ValueError("Unordered or duplicated diagnostic row")
            previous = key
            counts[category] += 1
            if sum(counts.values()) > summary.get(total_field, -1):
                raise ValueError("Excess diagnostic rows")
    if metadata is None or digest.hexdigest() != expected_digest:
        raise ValueError("Child report hash or metadata mismatch")
    expected_counts = (metadata["blockingByReason"] if is_history else {
        "incomplete": metadata["totalIncompleteEventCount"],
        "conflict": metadata["totalConflictEventCount"],
    })
    if (counts != expected_counts or sum(counts.values()) != metadata[total_field]
        or summary.get("exportSha256") != expected_digest
        or summary.get("snapshotSha256") != metadata["snapshotSha256"]
        or summary.get("asOf") != cutoff
        or summary.get("productionCoverageClaimed") is not False):
        raise ValueError("Child report totals or provenance mismatch")
    return metadata


def verify_bundle(path: Path, *, expected_sha256: str) -> dict[str, object]:
    """Verify custody digest, archive structure and every exported row; never certify origin."""
    if not _is_sha(expected_sha256):
        raise ValueError("An independently retained lowercase SHA-256 is required")
    path = Path(path)
    if not path.is_file() or path.is_symlink() or _sha256(path) != expected_sha256:
        raise ValueError("Evidence bundle custody SHA-256 mismatch")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 3 or set(names) != MEMBERS:
            raise ValueError("Unexpected, missing or duplicated ZIP members")
        for entry in archive.infolist():
            if (entry.is_dir() or entry.flag_bits & 1 or entry.file_size > 4 * 1024**3
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError("Unsafe ZIP member")
        if archive.getinfo(MANIFEST).file_size > MAX_MANIFEST_BYTES:
            raise ValueError("Oversized manifest")
        manifest = _json(archive.read(MANIFEST))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid manifest")
        try:
            cutoff = datetime.fromisoformat(manifest["asOf"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Invalid PIT cutoff") from None
        if (cutoff.tzinfo is None or cutoff.utcoffset() is None
            or cutoff.astimezone(timezone.utc) > datetime.now(timezone.utc)):
            raise ValueError("Invalid or future PIT cutoff")
        if (manifest.get("artifactVersion") != "athena-paired-operational-evidence-v1"
            or manifest.get("status") != "diagnostic_only"
            or manifest.get("sameSourceGeneration") is not True
            or not _is_sha(manifest.get("sourceGenerationSha256"))
            or any(manifest.get(flag) is not False for flag in (
                "operationalOriginVerified", "independentProviderAgreementVerified",
                "productionCoverageClaimed", "automaticBackfill",
                "automaticCanonicalization", "productionLearningEligible", "automaticTrading"))
            or not isinstance(manifest.get("members"), dict)
            or set(manifest["members"]) != {HISTORY, ACTIONS}):
            raise ValueError("Invalid or authority-escalating manifest")
        history = _verify_report(archive, HISTORY, manifest.get("history"),
                                 cutoff=manifest["asOf"], expected_digest=manifest["members"][HISTORY])
        actions = _verify_report(archive, ACTIONS, manifest.get("corporateActions"),
                                 cutoff=manifest["asOf"], expected_digest=manifest["members"][ACTIONS])
        # An independently rehashed child report is not sufficient: the two
        # reports must be attributable to the very same frozen generation
        # named by the manifest, not merely to individually valid snapshots.
        if (history["snapshotSha256"] != manifest["sourceGenerationSha256"]
            or actions["snapshotSha256"] != manifest["sourceGenerationSha256"]):
            raise ValueError("Paired diagnostic source generations do not match")
        if (history["eligibleInstrumentCount"] !=
            history["currentDeepHistoryInstrumentCount"] + history["totalBlockingCount"]
            or actions["totalUnresolvedEventCount"] !=
            actions["totalIncompleteEventCount"] + actions["totalConflictEventCount"]):
            raise ValueError("Inconsistent eligible-universe or action totals")
    return {
        "status": "paired_diagnostic_bundle_verified",
        "asOf": manifest["asOf"],
        "custodySha256Matched": True,
        "sourceGenerationSha256": manifest["sourceGenerationSha256"],
        "eligibleInstrumentCount": history["eligibleInstrumentCount"],
        "historyBlockingCount": history["totalBlockingCount"],
        "corporateActionUnresolvedCount": actions["totalUnresolvedEventCount"],
        "operationalOriginVerified": False,
        "independentProviderAgreementVerified": False,
        "productionCoverageClaimed": False,
        "productionAuthorization": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        result = verify_bundle(args.bundle, expected_sha256=args.expected_sha256)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, KeyError, TypeError):
        print(json.dumps({"status": "failed", "reason": "Evidence integrity or custody check failed"}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Publish history gaps and corporate-action conflicts from ONE frozen SQLite generation.

Diagnostic only: source origin and independent provider agreement are not attested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from scripts.export_corporate_action_reconciliation import (
    _consistent_copy, _cutoff, _sha256_file, _verify_snapshot_unchanged, export_worklist,
)
from scripts.export_market_history_gaps import PAGE_SIZE, export_history_gaps

HISTORY_MEMBER = "market_history_gaps.jsonl"
ACTIONS_MEMBER = "corporate_action_reconciliation.jsonl"
MANIFEST_MEMBER = "manifest.json"


def _metadata(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        result = json.loads(stream.readline())
    if not isinstance(result, dict) or result.get("recordType") != "metadata":
        raise RuntimeError("Missing diagnostic metadata")
    return result


def _member_sha(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_operational_history_bundle(
    *, database_path: Path, output_path: Path, as_of: datetime,
    history_page_size: int = PAGE_SIZE,
) -> dict[str, object]:
    cutoff = _cutoff(as_of)
    source = Path(database_path).expanduser().resolve()
    output = Path(output_path).expanduser().absolute()
    if output.resolve() == source or not output.parent.is_dir():
        raise ValueError("Output must differ from database and have an existing parent")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to overwrite existing evidence")
    staged = None
    try:
        with tempfile.TemporaryDirectory(prefix="athena-paired-evidence-") as folder:
            root = Path(folder)
            frozen = root / "generation.db"
            source_sha = _consistent_copy(source, frozen)
            history_path = root / HISTORY_MEMBER
            actions_path = root / ACTIONS_MEMBER
            history = export_history_gaps(
                database_path=frozen, output_path=history_path,
                as_of=cutoff, page_size=history_page_size,
            )
            actions = export_worklist(
                database_path=frozen, output_path=actions_path, as_of=cutoff,
            )
            _verify_snapshot_unchanged(frozen, source_sha)
            for summary, path, status in (
                (history, history_path, "complete_pit_history_diagnostic"),
                (actions, actions_path, "complete_pit_reconciliation_diagnostic"),
            ):
                meta = _metadata(path)
                if (
                    summary.get("asOf") != cutoff.isoformat()
                    or meta.get("asOf") != cutoff.isoformat()
                    or meta.get("status") != status
                    or meta.get("completeExport") is not True
                    or meta.get("productionCoverageClaimed") is not False
                    or summary.get("productionCoverageClaimed") is not False
                    or meta.get("snapshotSha256") != summary.get("snapshotSha256")
                    or summary.get("exportSha256") != _sha256_file(path)
                ):
                    raise RuntimeError("Paired diagnostic metadata mismatch")
            if (
                history["eligibleInstrumentCount"]
                != history["currentDeepHistoryInstrumentCount"] + history["totalBlockingCount"]
                or actions["totalUnresolvedEventCount"]
                != actions["totalIncompleteEventCount"] + actions["totalConflictEventCount"]
            ):
                raise RuntimeError("Paired diagnostic totals disagree")
            manifest = {
                "artifactVersion": "athena-paired-operational-evidence-v1",
                "asOf": cutoff.isoformat(),
                "status": "diagnostic_only",
                "sourceGenerationSha256": source_sha,
                "sameSourceGeneration": True,
                "history": history,
                "corporateActions": actions,
                "members": {
                    HISTORY_MEMBER: history["exportSha256"],
                    ACTIONS_MEMBER: actions["exportSha256"],
                },
                "operationalOriginVerified": False,
                "independentProviderAgreementVerified": False,
                "productionCoverageClaimed": False,
                "automaticBackfill": False,
                "automaticCanonicalization": False,
                "productionLearningEligible": False,
                "automaticTrading": False,
            }
            with tempfile.NamedTemporaryFile(
                mode="w+b", dir=output.parent, prefix=".athena-paired-", suffix=".tmp",
                delete=False,
            ) as stream:
                staged = Path(stream.name)
                with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(history_path, arcname=HISTORY_MEMBER)
                    archive.write(actions_path, arcname=ACTIONS_MEMBER)
                    archive.writestr(MANIFEST_MEMBER, json.dumps(
                        manifest, sort_keys=True, ensure_ascii=False,
                        allow_nan=False, separators=(",", ":"),
                    ) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            with zipfile.ZipFile(staged) as archive:
                if set(archive.namelist()) != {HISTORY_MEMBER, ACTIONS_MEMBER, MANIFEST_MEMBER}:
                    raise RuntimeError("Unexpected ZIP members")
                if any(_member_sha(archive, name) != sha for name, sha in manifest["members"].items()):
                    raise RuntimeError("ZIP member integrity mismatch")
                if json.loads(archive.read(MANIFEST_MEMBER)) != manifest:
                    raise RuntimeError("ZIP manifest integrity mismatch")
            _verify_snapshot_unchanged(frozen, source_sha)
            bundle_sha = _sha256_file(staged)
            os.link(staged, output)  # Publish the entire pair atomically; never overwrite.
        return {
            "status": "paired_diagnostic_bundle_written",
            "asOf": cutoff.isoformat(),
            "sourceGenerationSha256": source_sha,
            "bundleSha256": bundle_sha,
            "eligibleInstrumentCount": history["eligibleInstrumentCount"],
            "historyBlockingCount": history["totalBlockingCount"],
            "corporateActionUnresolvedCount": actions["totalUnresolvedEventCount"],
            "operationalOriginVerified": False,
            "productionCoverageClaimed": False,
            "automaticTrading": False,
        }
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--history-page-size", type=int, default=PAGE_SIZE)
    args = parser.parse_args()
    result = export_operational_history_bundle(
        database_path=args.database, output_path=args.output,
        as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")),
        history_page_size=args.history_page_size,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

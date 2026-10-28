"""Export every unresolved corporate action from one consistent SQLite snapshot.

Read-only against the supplied database. Does not fetch providers, backfill,
canonicalize, approve production readiness or claim off-site provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.corporate_action_reconciliation_worklist_service import (
    CorporateActionReconciliationWorklistService,
)


PAGE_SIZE = 500


def _cutoff(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    cutoff = value.astimezone(timezone.utc)
    if cutoff > datetime.now(timezone.utc):
        raise ValueError("as_of cannot be in the future")
    return cutoff


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _consistent_copy(source: Path, destination: Path) -> str:
    """SQLite online backup includes committed WAL data without writing to source."""
    if not source.is_file():
        raise FileNotFoundError("Authorized source SQLite database does not exist")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
        # Reject a wrong/empty database instead of initializing it as ATHENA.
        reader.execute("SELECT 1 FROM instruments LIMIT 1")
        reader.execute("SELECT 1 FROM corporate_actions LIMIT 1")
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)
            integrity = writer.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise RuntimeError("Consistent SQLite snapshot failed integrity check")
    return _sha256_file(destination)


def export_worklist(
    *,
    database_path: Path,
    output_path: Path,
    as_of: datetime,
) -> dict[str, object]:
    """Atomically publish a complete JSONL diagnostic, never replacing an export."""
    cutoff = _cutoff(as_of)
    source = Path(database_path).expanduser().resolve()
    output = Path(output_path).expanduser().absolute()
    if output.resolve() == source or not output.parent.is_dir():
        raise ValueError("Output must be a separate file in an existing directory")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to overwrite an existing reconciliation export")

    with tempfile.TemporaryDirectory(prefix="athena-ca-snapshot-") as work:
        snapshot = Path(work) / "snapshot.db"
        snapshot_sha = _consistent_copy(source, snapshot)
        worklist = CorporateActionReconciliationWorklistService(AthenaDatabase(snapshot))
        first = worklist.get_worklist(as_of=cutoff, limit=PAGE_SIZE, offset=0)
        incomplete = first.total_incomplete_event_count
        conflicts = first.total_conflict_event_count
        total = incomplete + conflicts
        metadata = {
            "recordType": "metadata",
            "status": "complete_pit_reconciliation_diagnostic",
            "asOf": cutoff.isoformat(),
            "snapshotSha256": snapshot_sha,
            "totalUnresolvedEventCount": total,
            "totalIncompleteEventCount": incomplete,
            "totalConflictEventCount": conflicts,
            "completeExport": True,
            "productionCoverageClaimed": False,
            "automaticCanonicalization": False,
            "automaticTrading": False,
        }
        staged: Path | None = None
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".athena-ca-export-", suffix=".jsonl",
                dir=output.parent, delete=False,
            ) as handle:
                staged = Path(handle.name)

                def write_record(row: dict[str, object]) -> None:
                    line = (
                        json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    ).encode("utf-8")
                    handle.write(line)
                    digest.update(line)

                write_record(metadata)
                offset = 0
                previous_identity: tuple[int, str, str] | None = None
                observed_incomplete = 0
                observed_conflicts = 0
                while offset < total:
                    # Each page is reconstructed from the SAME immutable snapshot.
                    # The worklist retains only the requested page in memory.
                    page = first if offset == 0 else worklist.get_worklist(
                        as_of=cutoff, limit=PAGE_SIZE, offset=offset
                    )
                    expected_size = min(PAGE_SIZE, total - offset)
                    if (
                        page.as_of != cutoff
                        or page.offset != offset
                        or page.limit != PAGE_SIZE
                        or page.total_incomplete_event_count != incomplete
                        or page.total_conflict_event_count != conflicts
                        or len(page.items) != expected_size
                    ):
                        raise RuntimeError("Inconsistent corporate-action worklist page")
                    for item in page.items:
                        identity = (item.instrument_id, item.action_type, item.effective_at)
                        if previous_identity is not None and identity <= previous_identity:
                            raise RuntimeError("Duplicate or out-of-order economic event")
                        previous_identity = identity
                        if item.reconciliation_status == "incomplete":
                            observed_incomplete += 1
                        elif item.reconciliation_status == "conflict":
                            observed_conflicts += 1
                        else:
                            raise RuntimeError("Unexpected reconciled event in worklist")
                        write_record(item.to_api_dict())
                    offset += len(page.items)
                if observed_incomplete != incomplete or observed_conflicts != conflicts:
                    raise RuntimeError("Corporate-action worklist totals changed during export")
                handle.flush()
                os.fsync(handle.fileno())
            # Exclusive publication: a concurrent export cannot be overwritten.
            os.link(staged, output)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    return {
        "status": "complete_reconciliation_export_written",
        "asOf": cutoff.isoformat(),
        "totalUnresolvedEventCount": total,
        "totalIncompleteEventCount": incomplete,
        "totalConflictEventCount": conflicts,
        "snapshotSha256": snapshot_sha,
        "exportSha256": digest.hexdigest(),
        "productionCoverageClaimed": False,
        "automaticCanonicalization": False,
        "automaticTrading": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Authorized SQLite database or snapshot")
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file; never overwritten")
    parser.add_argument("--as-of", required=True, help="Fixed PIT cutoff, ISO-8601 with timezone")
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    result = export_worklist(
        database_path=args.database, output_path=args.output, as_of=cutoff
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

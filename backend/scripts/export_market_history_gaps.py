"""Export complete PIT market-history gaps from an authorized consistent SQLite snapshot.

Read-only on the source. No provider requests, backfill, investment action,
production coverage assertion, or silent truncation of the eligible universe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from app.database.read_only_snapshot_database import ReadOnlySnapshotDatabase
from app.services.market_history_gap_service import MarketHistoryGapService
from app.services.market_observation_coverage_service import MarketObservationCoverageService
from scripts.export_corporate_action_reconciliation import (
    _consistent_copy, _cutoff, _verify_snapshot_unchanged,
)


PAGE_SIZE = 500
_REASON_ORDER = {
    "no_observations": 0,
    "insufficient_span": 1,
    "discontinuous_source": 2,
    "stale_source": 3,
}


def export_history_gaps(
    *,
    database_path: Path,
    output_path: Path,
    as_of: datetime,
    page_size: int = PAGE_SIZE,
) -> dict[str, object]:
    """Publish one complete, cross-reconciled JSONL report without overwriting."""
    cutoff = _cutoff(as_of)
    if type(page_size) is not int or not 1 <= page_size <= MarketHistoryGapService.MAX_LIMIT:
        raise ValueError("page_size must be between 1 and 1000")
    source = Path(database_path).expanduser().resolve()
    output = Path(output_path).expanduser().absolute()
    if output.resolve() == source or not output.parent.is_dir():
        raise ValueError("Output must be separate from the source in an existing directory")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Refusing to overwrite an existing history export")

    with tempfile.TemporaryDirectory(prefix="athena-history-snapshot-") as work:
        snapshot = Path(work) / "snapshot.db"
        snapshot_sha = _consistent_copy(source, snapshot)
        database = ReadOnlySnapshotDatabase(snapshot)
        coverage = MarketObservationCoverageService(database).get_report(as_of=cutoff)
        gaps = MarketHistoryGapService(database)
        first = gaps.get_report(as_of=cutoff, limit=page_size, offset=0)
        total = first.total_blocking_count
        eligible = coverage.history_eligible_instrument_count
        current = coverage.current_deep_history_instrument_count
        if total + current != eligible:
            raise RuntimeError("History gaps and current eligible coverage disagree")
        ready = eligible > 0 and total == 0 and coverage.current_history_depth_ready
        if coverage.current_history_depth_ready != ready:
            raise RuntimeError("History readiness and complete blocker count disagree")

        expected = {
            "no_observations": first.no_observations_count,
            "insufficient_span": first.insufficient_span_count,
            "discontinuous_source": first.discontinuous_source_count,
            "stale_source": first.stale_source_count,
        }
        if sum(expected.values()) != total:
            raise RuntimeError("History gap reason totals disagree")
        metadata = {
            "recordType": "metadata",
            "status": "complete_pit_history_diagnostic",
            "asOf": cutoff.isoformat(),
            "snapshotSha256": snapshot_sha,
            "eligibleInstrumentCount": eligible,
            "currentDeepHistoryInstrumentCount": current,
            "totalBlockingCount": total,
            "blockingByReason": expected,
            "minimumHistoryDays": first.minimum_history_days,
            "maximumSourceGapDays": first.maximum_source_gap_days,
            "historyReadyOnSnapshot": ready,
            "coverage": coverage.to_api_dict(),
            "completeExport": True,
            "productionCoverageClaimed": False,
            "automaticBackfill": False,
            "automaticTrading": False,
        }
        staged: Path | None = None
        digest = hashlib.sha256()
        observed = dict.fromkeys(expected, 0)
        seen_ids: set[int] = set()
        previous_key: tuple[int, str, int] | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".athena-history-export-", suffix=".jsonl",
                dir=output.parent, delete=False,
            ) as handle:
                staged = Path(handle.name)

                def write(row: dict[str, object]) -> None:
                    line = (json.dumps(
                        row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ) + "\n").encode("utf-8")
                    handle.write(line)
                    digest.update(line)

                write(metadata)
                offset = 0
                while offset < total:
                    page = first if offset == 0 else gaps.get_report(
                        as_of=cutoff, limit=page_size, offset=offset
                    )
                    if (
                        page.as_of != cutoff.isoformat()
                        or page.offset != offset
                        or page.limit != page_size
                        or page.total_blocking_count != total
                        or page.minimum_history_days != first.minimum_history_days
                        or page.maximum_source_gap_days != first.maximum_source_gap_days
                        or {
                            "no_observations": page.no_observations_count,
                            "insufficient_span": page.insufficient_span_count,
                            "discontinuous_source": page.discontinuous_source_count,
                            "stale_source": page.stale_source_count,
                        } != expected
                        or len(page.items) != min(page_size, total - offset)
                    ):
                        raise RuntimeError("Inconsistent history gap worklist page")
                    for item in page.items:
                        if item.reason not in expected:
                            raise RuntimeError("Unknown history gap reason")
                        key = (_REASON_ORDER[item.reason], item.symbol, item.instrument_id)
                        if (
                            item.instrument_id in seen_ids
                            or (previous_key is not None and key <= previous_key)
                        ):
                            raise RuntimeError("Duplicate or out-of-order history gap")
                        seen_ids.add(item.instrument_id)
                        previous_key = key
                        observed[item.reason] += 1
                        write({"recordType": "history_gap", **item.to_api_dict()})
                    offset += len(page.items)
                if observed != expected or len(seen_ids) != total:
                    raise RuntimeError("Incomplete history gap export")
                handle.flush()
                os.fsync(handle.fileno())
            # The reported SHA must describe the exact snapshot actually queried.
            _verify_snapshot_unchanged(snapshot, snapshot_sha)
            # Exclusive publication: never replace another operator's evidence.
            os.link(staged, output)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    return {
        "status": "complete_history_gap_export_written",
        "asOf": cutoff.isoformat(),
        "eligibleInstrumentCount": eligible,
        "currentDeepHistoryInstrumentCount": current,
        "totalBlockingCount": total,
        "historyReadyOnSnapshot": ready,
        "snapshotSha256": snapshot_sha,
        "exportSha256": digest.hexdigest(),
        "productionCoverageClaimed": False,
        "automaticBackfill": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--as-of", required=True, help="PIT ISO-8601 timestamp with timezone")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    result = export_history_gaps(
        database_path=args.database,
        output_path=args.output,
        as_of=cutoff,
        page_size=args.page_size,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

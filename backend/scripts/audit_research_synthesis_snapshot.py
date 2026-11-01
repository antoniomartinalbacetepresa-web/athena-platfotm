"""Read-only inventory of the persisted Research Cycle -> category -> ATHENA chain.

Only use a consistent, checkpointed SQLite *copy*. This intentionally does not
open the operational database through AthenaDatabase.initialize(), run models,
create research, or claim that stored evidence is valid production research.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TABLES = {
    "cycles": "athena_professional_research_cycles",
    "news": "athena_news_syntheses",
    "investors": "athena_investors_syntheses",
    "athena": "athena_research_syntheses",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row(conn: sqlite3.Connection, table: str, cycle_hash: str | None = None) -> sqlite3.Row | None:
    # Table names are exclusively from the fixed, internal _TABLES constant.
    if cycle_hash is None:
        return conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
    return conn.execute(
        f"SELECT * FROM {table} WHERE cycle_hash = ? ORDER BY id DESC LIMIT 1",
        (cycle_hash,),
    ).fetchone()


def _shape_errors(row: sqlite3.Row, kind: str) -> tuple[list[str], dict[str, Any] | None]:
    """Structural checks only; canonical repository revalidation is still required."""
    errors: list[str] = []
    for field in ("cycle_hash", "radar_hash") if kind != "cycles" else ("cycle_hash", "radar_hash"):
        if not _SHA256.fullmatch(str(row[field] or "")):
            errors.append(f"invalid_{field}")
    try:
        package = json.loads(row["package_json"])
    except (TypeError, ValueError):
        return errors + ["invalid_package_json"], None
    if not isinstance(package, dict):
        return errors + ["invalid_package_shape"], None
    if kind == "cycles":
        cycle = package.get("cycle")
        integrity = cycle.get("integrity") if isinstance(cycle, dict) else None
        if not isinstance(integrity, dict) or integrity.get("cycleHash") != row["cycle_hash"] or integrity.get("radarHash") != row["radar_hash"]:
            errors.append("cycle_integrity_fields_mismatch")
    else:
        if package.get("cycleHash") != row["cycle_hash"] or package.get("radarHash") != row["radar_hash"]:
            errors.append("synthesis_binding_fields_mismatch")
        if kind == "athena" and package.get("newsSynthesisHash") != row["news_synthesis_hash"]:
            if not (package.get("newsSynthesisHash") is None and row["news_synthesis_hash"] is None):
                errors.append("news_synthesis_binding_mismatch")
        canonical = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != row["synthesis_hash"]:
            errors.append("synthesis_package_hash_mismatch")
    return errors, package


def audit(snapshot: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    snapshot = snapshot.expanduser().resolve(strict=True)
    if not snapshot.is_file():
        raise ValueError("snapshot must be a regular file")
    digest = _sha256_file(snapshot)
    if expected_sha256 is not None:
        if not _SHA256.fullmatch(expected_sha256) or digest != expected_sha256:
            raise ValueError("snapshot SHA-256 does not match the trusted expected digest")

    # immutable=1 forbids WAL/shm sidecar creation; requires an offline,
    # consistent and checkpointed copy. Never point this at a live WAL DB.
    with sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            kind: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table in present else None
            for kind, table in _TABLES.items()
        }
        latest: dict[str, dict[str, Any] | None] = {}
        invalid: list[str] = []
        packages: dict[str, dict[str, Any] | None] = {}
        for kind, table in _TABLES.items():
            row = _row(conn, table) if table in present else None
            if row is None:
                latest[kind] = None
                continue
            errors, package = _shape_errors(row, kind)
            if errors:
                invalid.extend(f"{kind}:{error}" for error in errors)
            latest[kind] = {"cycleHash": row["cycle_hash"], "structuralChecksPassed": not errors}
            packages[kind] = package

        cycle = latest.get("cycles")
        chain: dict[str, Any] | None = None
        blockers: list[str] = []
        if not cycle:
            blockers.append("missing_persisted_research_cycle")
        else:
            cycle_hash = cycle["cycleHash"]
            radar = (packages.get("cycles") or {}).get("radar")
            candidates = radar.get("candidates") if isinstance(radar, dict) else None
            categories: set[str] = set()
            if isinstance(candidates, list):
                for candidate in candidates:
                    for evidence in candidate.get("evidence", []) if isinstance(candidate, dict) else []:
                        if isinstance(evidence, dict) and isinstance(evidence.get("category"), str):
                            categories.add(evidence["category"].strip().lower())
            chain = {"cycleHash": cycle_hash, "categoriesFromUnverifiedPackage": sorted(categories)}
            for kind in ("news", "investors", "athena"):
                table = _TABLES[kind]
                row = _row(conn, table, cycle_hash) if table in present else None
                errors, _ = _shape_errors(row, kind) if row is not None else ([], None)
                chain[kind] = {"persisted": row is not None, "structuralChecksPassed": bool(row) and not errors}
                if errors:
                    invalid.extend(f"latest_cycle_{kind}:{error}" for error in errors)
            if "news" in categories and not chain["news"]["persisted"]:
                blockers.append("missing_canonical_news_synthesis_for_latest_cycle")
            if "investors" in categories and not chain["investors"]["persisted"]:
                blockers.append("missing_canonical_investors_synthesis_for_latest_cycle")
            if not chain["athena"]["persisted"]:
                blockers.append("missing_athena_synthesis_for_latest_cycle")
        if invalid:
            blockers.append("stored_package_structural_or_hash_mismatch")
        for kind, count in counts.items():
            if count is None:
                blockers.append(f"missing_table_{kind}")
        if latest.get("news") is None:
            blockers.append("no_latest_news_synthesis_for_flutter")
        if latest.get("athena") is None:
            blockers.append("no_latest_athena_synthesis_for_flutter")

    return {
        "status": "blocked" if blockers else "inventory_complete_requires_canonical_revalidation",
        "snapshotSha256": digest,
        "expectedSnapshotSha256Matched": expected_sha256 is not None,
        "snapshotConsistencyVerified": False,
        "readOnly": True,
        "canonicalInputAndSourceProvenanceVerified": False,
        "productionEligible": False,
        "recommendationInfluence": False,
        "automaticTrading": False,
        "counts": counts,
        "latest": latest,
        "latestCycleChain": chain,
        "structuralErrors": sorted(set(invalid)),
        "blockers": sorted(set(blockers)),
        "nextAction": (
            "obtain_a_verified_consistent_snapshot_and_fix_structural_errors"
            if invalid else
            "persist_an_authentic_pit_research_cycle_before_any_model_synthesis"
            if cycle is None else
            "complete_required_category_syntheses_then_athena_with_real_model_provenance_and_revalidate_via_http"
            if blockers else
            "verify_latest_http_endpoints_and_external_model_execution_provenance"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only inventory of research synthesis in an offline SQLite snapshot")
    parser.add_argument("--snapshot", type=Path, required=True, help="Consistent, checkpointed copy; NEVER a live WAL database")
    parser.add_argument("--expected-sha256", help="Trusted SHA-256 of the offline snapshot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit(args.snapshot, expected_sha256=args.expected_sha256)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "error", "readOnly": True, "errorType": type(exc).__name__, "productionEligible": False}), file=sys.stdout)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if not report["structuralErrors"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

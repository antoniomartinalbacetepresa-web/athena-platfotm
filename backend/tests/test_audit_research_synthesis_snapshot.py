"""Regression coverage for the offline, no-write research synthesis inventory."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.audit_research_synthesis_snapshot import audit, main


HASH_A = "a" * 64
HASH_B = "b" * 64


def _snapshot(tmp_path: Path, *, with_cycle: bool = False, categories: tuple[str, ...] = ("news",)) -> Path:
    path = tmp_path / "snapshot.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE athena_professional_research_cycles (id INTEGER PRIMARY KEY, cycle_hash TEXT, radar_hash TEXT, package_json TEXT);
            CREATE TABLE athena_news_syntheses (id INTEGER PRIMARY KEY, cycle_hash TEXT, radar_hash TEXT, synthesis_hash TEXT, package_json TEXT);
            CREATE TABLE athena_investors_syntheses (id INTEGER PRIMARY KEY, cycle_hash TEXT, radar_hash TEXT, synthesis_hash TEXT, package_json TEXT);
            CREATE TABLE athena_research_syntheses (id INTEGER PRIMARY KEY, cycle_hash TEXT, radar_hash TEXT, news_synthesis_hash TEXT, synthesis_hash TEXT, package_json TEXT);
        """)
        if with_cycle:
            package = {
                "cycle": {"integrity": {"cycleHash": HASH_A, "radarHash": HASH_B}},
                "radar": {"candidates": [{"evidence": [{"category": category} for category in categories]}]},
            }
            conn.execute(
                "INSERT INTO athena_professional_research_cycles VALUES (1, ?, ?, ?)",
                (HASH_A, HASH_B, json.dumps(package)),
            )
    return path


def _add_synthesis(path: Path, kind: str, *, cycle_hash: str = HASH_A, radar_hash: str = HASH_B) -> None:
    package = {"cycleHash": cycle_hash, "radarHash": radar_hash, "synthesis": {"status": "test_only"}}
    canonical = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    table = {"news": "athena_news_syntheses", "investors": "athena_investors_syntheses", "athena": "athena_research_syntheses"}[kind]
    with sqlite3.connect(path) as conn:
        if kind == "athena":
            conn.execute(f"INSERT INTO {table} VALUES (1, ?, ?, NULL, ?, ?)", (cycle_hash, radar_hash, digest, canonical))
        else:
            conn.execute(f"INSERT INTO {table} VALUES (1, ?, ?, ?, ?)", (cycle_hash, radar_hash, digest, canonical))


def test_empty_snapshot_reports_missing_cycle_and_both_latest_without_writes(tmp_path):
    path = _snapshot(tmp_path)
    before = path.read_bytes()
    report = audit(path)
    assert report["counts"] == {"cycles": 0, "news": 0, "investors": 0, "athena": 0}
    assert "missing_persisted_research_cycle" in report["blockers"]
    assert "no_latest_news_synthesis_for_flutter" in report["blockers"]
    assert report["canonicalInputAndSourceProvenanceVerified"] is False
    assert path.read_bytes() == before
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-shm").exists()


def test_cycle_reports_missing_required_news_and_athena(tmp_path):
    path = _snapshot(tmp_path, with_cycle=True)
    report = audit(path)
    assert report["latestCycleChain"]["categoriesFromUnverifiedPackage"] == ["news"]
    assert "missing_canonical_news_synthesis_for_latest_cycle" in report["blockers"]
    assert "missing_athena_synthesis_for_latest_cycle" in report["blockers"]


def test_investors_dependency_only_when_category_present(tmp_path):
    path = _snapshot(tmp_path, with_cycle=True, categories=("technical", "investors"))
    report = audit(path)
    assert "missing_canonical_investors_synthesis_for_latest_cycle" in report["blockers"]
    assert "missing_canonical_news_synthesis_for_latest_cycle" not in report["blockers"]


def test_complete_inventory_does_not_claim_verified_provenance(tmp_path):
    path = _snapshot(tmp_path, with_cycle=True, categories=("news", "investors"))
    for kind in ("news", "investors", "athena"):
        _add_synthesis(path, kind)
    report = audit(path)
    assert report["blockers"] == []
    assert report["status"] == "inventory_complete_requires_canonical_revalidation"
    assert report["canonicalInputAndSourceProvenanceVerified"] is False
    assert report["productionEligible"] is False
    assert report["latest"]["athena"]["structuralChecksPassed"] is True


def test_tampered_synthesis_hash_fails_closed(tmp_path):
    path = _snapshot(tmp_path, with_cycle=True)
    _add_synthesis(path, "news")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE athena_news_syntheses SET synthesis_hash = ?", (HASH_A,))
    report = audit(path)
    assert "stored_package_structural_or_hash_mismatch" in report["blockers"]
    assert "news:synthesis_package_hash_mismatch" in report["structuralErrors"]
    assert main(["--snapshot", str(path)]) == 3


def test_expected_digest_mismatch_fails_before_opening_snapshot(tmp_path):
    path = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        audit(path, expected_sha256=HASH_A)
    assert main(["--snapshot", str(path), "--expected-sha256", HASH_A]) == 2


def test_missing_schema_is_explicit_not_silent(tmp_path):
    path = tmp_path / "empty.db"
    with sqlite3.connect(path):
        pass
    report = audit(path)
    assert "missing_table_cycles" in report["blockers"]
    assert report["counts"]["cycles"] is None


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_inventory_rejects_sqlite_sidecars_even_with_valid_main_file_digest(tmp_path, suffix):
    path = _snapshot(tmp_path, with_cycle=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path) + suffix).write_bytes(b"uncheckpointed-sidecar")
    with pytest.raises(ValueError, match="SQLite sidecars"):
        audit(path, expected_sha256=digest)
    assert main(["--snapshot", str(path), "--expected-sha256", digest]) == 2


def test_inventory_rejects_committed_wal_rows_hidden_from_immutable_reader(tmp_path):
    path = _snapshot(tmp_path, with_cycle=True)
    with closing(sqlite3.connect(path)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        writer.execute(
            "UPDATE athena_professional_research_cycles SET radar_hash = ?",
            ("0" * 64,),
        )
        writer.commit()
        assert Path(str(path) + "-wal").exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        with pytest.raises(ValueError, match="SQLite sidecars"):
            audit(path, expected_sha256=digest)
        assert main(["--snapshot", str(path), "--expected-sha256", digest]) == 2

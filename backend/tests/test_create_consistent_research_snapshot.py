"""Offline SQLite backup regressions; fixtures are not operational evidence."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.create_consistent_research_snapshot import export_snapshot, main


def _source(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, summary TEXT NOT NULL)")
        conn.execute("INSERT INTO evidence (summary) VALUES ('initial')")
        conn.commit()


def test_online_backup_includes_committed_wal_rows_without_changing_source(tmp_path):
    source = tmp_path / "live.db"
    destination = tmp_path / "secure.db"
    _source(source)
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        main_before = hashlib.sha256(source.read_bytes()).hexdigest()
        writer.execute("INSERT INTO evidence (summary) VALUES ('committed-in-wal')")
        writer.commit()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == main_before
        assert Path(str(source) + "-wal").exists()
        report = export_snapshot(source, destination, acknowledge_sensitive_copy=True)
        assert report["status"] == "consistent_snapshot_created"
        assert report["snapshotSha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
        assert report["independentCustodyVerified"] is False
        assert report["productionEligible"] is False
        with closing(sqlite3.connect(f"{destination.as_uri()}?mode=ro&immutable=1", uri=True)) as snapshot:
            assert snapshot.execute("SELECT summary FROM evidence ORDER BY id").fetchall() == [
                ("initial",), ("committed-in-wal",)
            ]
        assert all(not Path(str(destination) + s).exists() for s in ("-wal", "-shm", "-journal"))


def test_sensitive_copy_requires_explicit_acknowledgement(tmp_path):
    source = tmp_path / "live.db"
    destination = tmp_path / "secure.db"
    _source(source)
    with pytest.raises(ValueError, match="autorización explícita"):
        export_snapshot(source, destination)
    assert not destination.exists()


def test_existing_snapshot_never_overwritten(tmp_path):
    source = tmp_path / "live.db"
    destination = tmp_path / "secure.db"
    _source(source)
    destination.write_bytes(b"existing")
    with pytest.raises(ValueError, match="ya existe"):
        export_snapshot(source, destination, acknowledge_sensitive_copy=True)
    assert destination.read_bytes() == b"existing"


def test_corrupt_source_fails_without_publishing_destination(tmp_path):
    source = tmp_path / "broken.db"
    destination = tmp_path / "secure.db"
    source.write_bytes(b"not sqlite")
    assert main(["--source", str(source), "--destination", str(destination), "--acknowledge-sensitive-copy"]) == 2
    assert not destination.exists()
    assert list(tmp_path.glob(".athena-research-*")) == []


def test_cli_reports_digest_without_paths_or_private_rows(tmp_path, capsys):
    source = tmp_path / "live.db"
    destination = tmp_path / "secure.db"
    _source(source)
    assert main(["--source", str(source), "--destination", str(destination), "--acknowledge-sensitive-copy"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "consistent_snapshot_created"
    assert "live.db" not in json.dumps(payload)
    assert "initial" not in json.dumps(payload)
    assert payload["snapshotSha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()

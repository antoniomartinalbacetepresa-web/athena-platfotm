from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts.run_database_backup import run_backup


def _configure(monkeypatch, database_path: Path, backup_directory: Path, keep_last: str = "2") -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("ATHENA_BACKUP_DIRECTORY", str(backup_directory))
    monkeypatch.setenv("ATHENA_BACKUP_KEEP_LAST", keep_last)


def test_runner_creates_verified_backup_and_applies_retention(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "live" / "athena.db"
    backup_directory = tmp_path / "backups"
    _configure(monkeypatch, database_path, backup_directory, "1")
    AthenaDatabase(database_path).initialize()

    first = run_backup()
    second = run_backup()

    backups = sorted(backup_directory.glob("athena-*.db"))
    manifests = sorted(backup_directory.glob("athena-*.db.manifest.json"))
    assert len(backups) == len(manifests) == 1
    assert first["status"] == second["status"] == "ok"
    assert second["sha256Verified"] is True
    assert second["policy"] == {
        "scheduledExecutionVerified": False,
        "offsiteCopyVerified": False,
        "restoreDrillOperationallyVerified": False,
    }
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["sha256"]
    assert manifest["size_bytes"] > 0


def test_runner_fails_closed_without_destination(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "live" / "athena.db"
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(database_path))
    monkeypatch.delenv("ATHENA_BACKUP_DIRECTORY", raising=False)
    monkeypatch.setenv("ATHENA_BACKUP_KEEP_LAST", "2")
    AthenaDatabase(database_path).initialize()

    with pytest.raises(RuntimeError, match="ATHENA_BACKUP_DIRECTORY"):
        run_backup()


def test_runner_rejects_live_database_directory_and_invalid_retention(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    _configure(monkeypatch, database_path, database_path.parent, "0")

    with pytest.raises(RuntimeError, match="directorio"):
        run_backup()

    _configure(monkeypatch, database_path, tmp_path / "backups", "0")
    with pytest.raises(RuntimeError, match="KEEP_LAST"):
        run_backup()

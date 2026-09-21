from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts.copy_verified_backup_secondary import copy_verified_backup
from scripts.run_verified_backup_cycle import run_cycle


def _seed(path: Path) -> None:
    database = AthenaDatabase(path)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS recovery_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO recovery_probe (id, value) VALUES (?, ?)",
            (1, "durable"),
        )


def test_verified_cycle_then_secondary_copy_preserves_fail_closed_policy(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    _seed(database_path)

    cycle = run_cycle(
        database_path=database_path,
        backup_directory=primary,
        keep_last=2,
        prefix="athena-",
        now=datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc),
    )

    assert cycle["status"] == "verified_backup_cycle_passed"
    assert cycle["policy"] == {
        "integrityVerified": True,
        "restoreDrillVerified": True,
        "offsiteBackupVerified": False,
        "scheduledExecutionVerified": False,
        "productionRecoveryVerified": False,
    }

    copied = copy_verified_backup(
        backup_path=Path(str(cycle["backup"])),
        manifest_path=Path(str(cycle["manifest"])),
        destination_directory=secondary,
    )

    assert copied["status"] == "secondary_copy_verified"
    assert copied["policy"] == {
        "secondaryCopyVerified": True,
        "offsiteLocationVerified": False,
        "scheduledExecutionVerified": False,
        "productionRecoveryVerified": False,
    }
    assert Path(str(copied["backup"])).read_bytes() == Path(str(cycle["backup"])).read_bytes()


def test_secondary_copy_rejects_tampered_primary_without_writing_destination(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    _seed(database_path)
    cycle = run_cycle(
        database_path=database_path,
        backup_directory=primary,
        keep_last=1,
        prefix="athena-",
        now=datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc),
    )
    backup = Path(str(cycle["backup"]))
    backup.write_bytes(backup.read_bytes() + b"tampered")

    with pytest.raises(RuntimeError, match="manifiesto"):
        copy_verified_backup(
            backup_path=backup,
            manifest_path=Path(str(cycle["manifest"])),
            destination_directory=secondary,
        )

    assert not secondary.exists()


def test_secondary_copy_rejects_manifest_without_valid_sha256(tmp_path: Path) -> None:
    backup = tmp_path / "primary" / "athena.db"
    manifest = tmp_path / "primary" / "athena.db.manifest.json"
    destination = tmp_path / "secondary"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"backup")
    manifest.write_text(json.dumps({"sha256": "not-a-sha"}), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        copy_verified_backup(
            backup_path=backup,
            manifest_path=manifest,
            destination_directory=destination,
        )

    assert not destination.exists()

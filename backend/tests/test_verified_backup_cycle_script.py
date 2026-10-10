from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts.run_verified_backup_cycle import run_cycle


def test_verified_backup_cycle_creates_verifies_drills_and_retains(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    database = AthenaDatabase(database_path)
    database.initialize()
    backup_directory = tmp_path / "backups"

    first = run_cycle(
        database_path=database_path,
        backup_directory=backup_directory,
        keep_last=1,
        prefix="athena-",
        now=datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
    )
    second = run_cycle(
        database_path=database_path,
        backup_directory=backup_directory,
        keep_last=1,
        prefix="athena-",
        now=datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc),
    )

    assert first["status"] == "verified_backup_cycle_passed"
    assert second["status"] == "verified_backup_cycle_passed"
    assert second["policy"] == {
        "integrityVerified": True,
        "restoreDrillVerified": True,
        "offsiteBackupVerified": False,
        "scheduledExecutionVerified": False,
        "productionRecoveryVerified": False,
    }
    assert Path(second["backup"]).is_file()
    assert Path(second["manifest"]).is_file()
    assert not Path(first["backup"]).exists()
    assert second["retention"]["kept"] == [second["backup"]]
    assert second["retention"]["deleted"] == [first["backup"]]


def test_verified_backup_cycle_rejects_unsafe_retention_before_writing(tmp_path: Path) -> None:
    database_path = tmp_path / "athena.db"
    AthenaDatabase(database_path).initialize()

    with pytest.raises(ValueError, match="al menos un backup"):
        run_cycle(
            database_path=database_path,
            backup_directory=tmp_path / "backups",
            keep_last=0,
            prefix="athena-",
        )

    assert not (tmp_path / "backups").exists()

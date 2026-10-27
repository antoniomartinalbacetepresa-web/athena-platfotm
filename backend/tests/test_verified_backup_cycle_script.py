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


def test_integrated_secondary_copy_precedes_primary_retention(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"
    secondary = tmp_path / "independent"
    first = run_cycle(
        database_path=database_path, backup_directory=primary, keep_last=1,
        prefix="athena-", now=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
        secondary_directory=secondary, offsite_attested=True,
    )
    second = run_cycle(
        database_path=database_path, backup_directory=primary, keep_last=1,
        prefix="athena-", now=datetime(2026, 9, 20, 11, tzinfo=timezone.utc),
        secondary_directory=secondary,
    )
    assert first["secondary"]["status"] == "secondary_copy_verified"
    assert first["secondary"]["restore_drill"]["schema_version"] > 0
    assert first["secondary"]["policy"]["offsiteLocationOperatorAttested"] is True
    assert first["secondary"]["policy"]["offsiteLocationVerified"] is False
    assert first["policy"]["offsiteBackupVerified"] is False
    assert Path(first["secondary"]["backup"]).is_file()
    assert Path(first["secondary"]["manifest"]).is_file()
    assert Path(second["secondary"]["backup"]).is_file()
    assert Path(second["backup"]).is_file()
    assert not Path(first["backup"]).exists()
    assert second["retention"]["deleted"] == [first["backup"]]


def test_secondary_failure_preserves_previous_primary_recovery_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_verified_backup_cycle as backup_script

    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"
    first = run_cycle(
        database_path=database_path, backup_directory=primary, keep_last=1,
        prefix="athena-", now=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
    )

    def reject_secondary(**kwargs: object) -> None:
        raise RuntimeError("secondary storage unavailable")

    monkeypatch.setattr(backup_script, "copy_verified_backup", reject_secondary)
    with pytest.raises(RuntimeError, match="secondary storage unavailable"):
        run_cycle(
            database_path=database_path, backup_directory=primary, keep_last=1,
            prefix="athena-", now=datetime(2026, 9, 20, 11, tzinfo=timezone.utc),
            secondary_directory=tmp_path / "independent",
        )
    assert Path(first["backup"]).is_file()
    assert Path(first["manifest"]).is_file()
    assert (primary / "athena-20260920T110000Z.db").is_file()


def test_integrated_cycle_rejects_nested_secondary_before_writing(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"
    with pytest.raises(ValueError, match="independiente"):
        run_cycle(
            database_path=database_path, backup_directory=primary, keep_last=1,
            prefix="athena-", secondary_directory=primary / "nested",
        )
    assert not primary.exists()


def test_integrated_cycle_rejects_offsite_attestation_without_copy(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    with pytest.raises(ValueError, match="destino secundario"):
        run_cycle(
            database_path=tmp_path / "missing.db", backup_directory=primary,
            keep_last=1, prefix="athena-", offsite_attested=True,
        )
    assert not primary.exists()

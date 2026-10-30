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


def test_integrated_cycle_rejects_live_database_directory_before_writing(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    with pytest.raises(ValueError, match="backup primario"):
        run_cycle(
            database_path=database_path, backup_directory=database_path.parent,
            keep_last=1, prefix="athena-",
        )
    assert not list(database_path.parent.glob("athena-*.db"))


def test_integrated_cycle_rejects_secondary_in_live_database_directory_before_writing(tmp_path: Path) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"
    with pytest.raises(ValueError, match="destino secundario"):
        run_cycle(
            database_path=database_path, backup_directory=primary,
            secondary_directory=database_path.parent, keep_last=1, prefix="athena-",
        )
    assert not primary.exists()


@pytest.mark.parametrize("relative_primary", ["shared", "shared/live/backups"])
def test_cycle_rejects_primary_ancestor_or_descendant_of_live_directory(
    tmp_path: Path, relative_primary: str,
) -> None:
    database_path = tmp_path / "shared" / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / relative_primary

    with pytest.raises(ValueError, match="backup primario"):
        run_cycle(
            database_path=database_path, backup_directory=primary,
            keep_last=1, prefix="athena-",
        )

    assert not list(tmp_path.rglob("athena-*.db"))
    assert not (primary / "athena-20260920T100000Z.db").exists()


@pytest.mark.parametrize("relative_secondary", ["shared", "shared/live/secondary"])
def test_cycle_rejects_secondary_ancestor_or_descendant_of_live_directory(
    tmp_path: Path, relative_secondary: str,
) -> None:
    database_path = tmp_path / "shared" / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"
    secondary = tmp_path / relative_secondary

    with pytest.raises(ValueError, match="destino secundario"):
        run_cycle(
            database_path=database_path, backup_directory=primary,
            secondary_directory=secondary, keep_last=1, prefix="athena-",
        )

    assert not primary.exists()
    assert not list(tmp_path.rglob("athena-*.db"))



@pytest.mark.parametrize("unsafe_prefix", ["athena-*", "athena-?", "athena-[old]", "athena-/"])
def test_cycle_rejects_unsafe_retention_prefix_before_creating_backup(
    tmp_path: Path, unsafe_prefix: str,
) -> None:
    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary = tmp_path / "primary"

    with pytest.raises(ValueError, match="prefijo"):
        run_cycle(
            database_path=database_path,
            backup_directory=primary,
            keep_last=1,
            prefix=unsafe_prefix,
        )

    assert not primary.exists()


def test_secondary_guard_requires_secondary_destination_before_writing(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    with pytest.raises(ValueError, match="secondary guard"):
        run_cycle(
            database_path=tmp_path / "missing.db",
            backup_directory=primary, keep_last=1, prefix="athena-",
            secondary_guard=lambda: None,
        )
    assert not primary.exists()



def test_mount_loss_during_secondary_retention_preserves_previous_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.database_backup_service import DatabaseBackupService
    from scripts import run_verified_backup_cycle as cycle

    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    state = {"mounted": True, "secondary_retention": False}

    def mount_guard() -> None:
        if not state["mounted"]:
            raise RuntimeError("Secondary mount disappeared during retention")

    first = run_cycle(
        database_path=database_path, backup_directory=primary,
        secondary_directory=secondary, keep_last=1, secondary_keep_last=1,
        prefix="athena-", now=datetime(2026, 10, 30, 10, tzinfo=timezone.utc),
        secondary_guard=mount_guard,
    )
    original_retention = DatabaseBackupService.apply_retention
    original_verify = DatabaseBackupService.verify_backup

    def guarded_retention(self, directory, *, keep_last, filename_prefix="athena-", guard=None):
        state["secondary_retention"] = Path(directory) == secondary
        try:
            return original_retention(
                self, directory, keep_last=keep_last,
                filename_prefix=filename_prefix, guard=guard,
            )
        finally:
            state["secondary_retention"] = False

    def verify_then_lose_mount(self, backup_path):
        result = original_verify(self, backup_path)
        if state["secondary_retention"]:
            state["mounted"] = False
        return result

    monkeypatch.setattr(DatabaseBackupService, "apply_retention", guarded_retention)
    monkeypatch.setattr(DatabaseBackupService, "verify_backup", verify_then_lose_mount)
    with pytest.raises(RuntimeError, match="mount disappeared during retention"):
        run_cycle(
            database_path=database_path, backup_directory=primary,
            secondary_directory=secondary, keep_last=1, secondary_keep_last=1,
            prefix="athena-", now=datetime(2026, 10, 30, 11, tzinfo=timezone.utc),
            secondary_guard=mount_guard,
        )
    assert Path(first["backup"]).is_file()
    assert Path(first["secondary"]["backup"]).is_file()
    assert len(list(primary.glob("athena-*.db"))) == 2
    assert len(list(secondary.glob("athena-*.db"))) == 2


def test_mount_loss_during_primary_retention_preserves_previous_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.database_backup_service import DatabaseBackupService

    database_path = tmp_path / "live" / "athena.db"
    AthenaDatabase(database_path).initialize()
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    state = {"mounted": True, "primary_retention": False}

    def mount_guard() -> None:
        if not state["mounted"]:
            raise RuntimeError("Secondary mount disappeared during primary retention")

    first = run_cycle(
        database_path=database_path, backup_directory=primary,
        secondary_directory=secondary, keep_last=1,
        prefix="athena-", now=datetime(2026, 10, 30, 10, tzinfo=timezone.utc),
        secondary_guard=mount_guard,
    )
    original_retention = DatabaseBackupService.apply_retention
    original_verify = DatabaseBackupService.verify_backup

    def guarded_retention(self, directory, *, keep_last, filename_prefix="athena-", guard=None):
        state["primary_retention"] = Path(directory) == primary
        try:
            return original_retention(
                self, directory, keep_last=keep_last,
                filename_prefix=filename_prefix, guard=guard,
            )
        finally:
            state["primary_retention"] = False

    def verify_then_lose_mount(self, backup_path):
        result = original_verify(self, backup_path)
        if state["primary_retention"]:
            state["mounted"] = False
        return result

    monkeypatch.setattr(DatabaseBackupService, "apply_retention", guarded_retention)
    monkeypatch.setattr(DatabaseBackupService, "verify_backup", verify_then_lose_mount)
    with pytest.raises(RuntimeError, match="mount disappeared during primary retention"):
        run_cycle(
            database_path=database_path, backup_directory=primary,
            secondary_directory=secondary, keep_last=1,
            prefix="athena-", now=datetime(2026, 10, 30, 11, tzinfo=timezone.utc),
            secondary_guard=mount_guard,
        )
    assert Path(first["backup"]).is_file()
    assert len(list(primary.glob("athena-*.db"))) == 2

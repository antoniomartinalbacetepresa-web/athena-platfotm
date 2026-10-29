from __future__ import annotations

from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from scripts import scheduled_verified_backup as scheduled


def _configured(tmp_path: Path) -> tuple[scheduled.ScheduledBackupConfig, Path]:
    database = tmp_path / "live" / "athena.db"
    AthenaDatabase(database).initialize()
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    lock_root = tmp_path / "run"
    lock_root.mkdir()
    return scheduled.ScheduledBackupConfig(database, primary, secondary, 3), lock_root / "lock"


def test_scheduler_rejects_missing_or_relative_paths_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="configuration"):
        scheduled.load_config({})
    with pytest.raises(ValueError, match="absolute"):
        scheduled.load_config({
            "ATHENA_BACKUP_DATABASE": "relative.db",
            "ATHENA_BACKUP_PRIMARY_DIRECTORY": str(tmp_path / "primary"),
            "ATHENA_BACKUP_SECONDARY_DIRECTORY": str(tmp_path / "secondary"),
        })


def test_scheduler_rejects_secondary_directory_without_mount(tmp_path: Path) -> None:
    config, lock = _configured(tmp_path)
    with pytest.raises(RuntimeError, match="mount"):
        scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert not list(config.primary.iterdir())
    assert not list(config.secondary.iterdir())


def test_scheduler_rejects_same_filesystem_even_when_mount_is_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, lock = _configured(tmp_path)
    monkeypatch.setattr(Path, "is_mount", lambda self: self == config.secondary)
    with pytest.raises(RuntimeError, match="mount"):
        scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert not list(config.primary.iterdir())


def test_scheduler_runs_verified_secondary_restore_and_never_claims_offsite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, lock = _configured(tmp_path)
    # A test-only independent mount substitute; NOT operational off-site proof.
    monkeypatch.setattr(scheduled, "require_independent_mount", lambda _: None)
    result = scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert result["status"] == "scheduled_entrypoint_cycle_passed"
    assert result["secondaryCopyAndRestoreVerified"] is True
    assert result["offsiteLocationVerified"] is False
    assert result["scheduledExecutionVerified"] is False
    assert result["productionRecoveryVerified"] is False
    assert len(list(config.primary.glob("athena-*.db"))) == 1
    assert len(list(config.secondary.glob("athena-*.db"))) == 1


def test_scheduler_lock_rejects_concurrent_invocation(tmp_path: Path) -> None:
    import fcntl

    config, lock = _configured(tmp_path)
    with lock.open("a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert not list(config.primary.iterdir())

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


def test_scheduler_requires_explicit_encrypted_secondary_storage_confirmation(
    tmp_path: Path,
) -> None:
    config, _ = _configured(tmp_path)
    environment = {
        "ATHENA_BACKUP_DATABASE": str(config.database),
        "ATHENA_BACKUP_PRIMARY_DIRECTORY": str(config.primary),
        "ATHENA_BACKUP_SECONDARY_DIRECTORY": str(config.secondary),
    }
    with pytest.raises(ValueError, match="Encrypted secondary"):
        scheduled.load_config(environment)
    loaded = scheduled.load_config({
        **environment, "ATHENA_BACKUP_ENCRYPTED_STORAGE_CONFIRMED": "true",
    })
    assert loaded == scheduled.ScheduledBackupConfig(
        config.database, config.primary, config.secondary, 7,
    )


def test_scheduler_rejects_unsafe_secondary_retention_configuration(
    tmp_path: Path,
) -> None:
    config, _ = _configured(tmp_path)
    environment = {
        "ATHENA_BACKUP_DATABASE": str(config.database),
        "ATHENA_BACKUP_PRIMARY_DIRECTORY": str(config.primary),
        "ATHENA_BACKUP_SECONDARY_DIRECTORY": str(config.secondary),
        "ATHENA_BACKUP_ENCRYPTED_STORAGE_CONFIRMED": "true",
        "ATHENA_BACKUP_KEEP_LAST": "3",
    }
    with pytest.raises(ValueError, match="Secondary retention"):
        scheduled.load_config({
            **environment, "ATHENA_BACKUP_SECONDARY_KEEP_LAST": "2",
        })
    with pytest.raises(ValueError, match="secondary backup retention"):
        scheduled.load_config({
            **environment, "ATHENA_BACKUP_SECONDARY_KEEP_LAST": "invalid",
        })
    assert scheduled.load_config(environment).secondary_keep_last is None
    assert scheduled.load_config({
        **environment, "ATHENA_BACKUP_SECONDARY_KEEP_LAST": "24",
    }).secondary_keep_last == 24


def test_scheduler_bounds_secondary_copies_only_when_explicitly_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from datetime import datetime, timezone

    config, lock = _configured(tmp_path)
    config = replace(config, keep_last=2, secondary_keep_last=3)
    monkeypatch.setattr(scheduled, "require_independent_mount", lambda _: None)
    original = scheduled.run_cycle
    times = iter([
        datetime(2026, 10, 29, hour, tzinfo=timezone.utc)
        for hour in (8, 9, 10, 11)
    ])

    def timed_cycle(**kwargs: object) -> dict[str, object]:
        return original(**kwargs, now=next(times))

    monkeypatch.setattr(scheduled, "run_cycle", timed_cycle)
    for _ in range(4):
        result = scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert result["secondaryRetentionConfigured"] is True
    assert result["secondaryRetentionDeleted"] == 1
    assert len(list(config.primary.glob("athena-*.db"))) == 2
    assert len(list(config.secondary.glob("athena-*.db"))) == 3


def test_secondary_retention_failure_preserves_primary_recovery_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from datetime import datetime, timezone

    from app.services.database_backup_service import DatabaseBackupService

    config, lock = _configured(tmp_path)
    config = replace(config, secondary_keep_last=3)
    monkeypatch.setattr(scheduled, "require_independent_mount", lambda _: None)
    original_cycle = scheduled.run_cycle

    def timed_cycle(**kwargs: object) -> dict[str, object]:
        return original_cycle(
            **kwargs, now=datetime(2026, 10, 29, 12, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(scheduled, "run_cycle", timed_cycle)
    original_retention = DatabaseBackupService.apply_retention
    directories: list[Path] = []

    def guarded_retention(self: DatabaseBackupService, directory: Path, *,
                          keep_last: int, filename_prefix: str = "athena-",
                          guard=None):
        directories.append(Path(directory))
        if Path(directory) == config.secondary:
            raise RuntimeError("Secondary retention failed")
        return original_retention(
            self, directory, keep_last=keep_last,
            filename_prefix=filename_prefix, guard=guard,
        )

    monkeypatch.setattr(DatabaseBackupService, "apply_retention", guarded_retention)
    with pytest.raises(RuntimeError, match="Secondary retention failed"):
        scheduled.run_scheduled_cycle(config, lock_path=lock)
    assert directories == [config.secondary]
    assert len(list(config.primary.glob("athena-*.db"))) == 1
    assert len(list(config.secondary.glob("athena-*.db"))) == 1


def test_mount_loss_after_secondary_copy_preserves_older_primary_recovery_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from datetime import datetime, timezone

    from scripts import run_verified_backup_cycle as cycle

    config, lock = _configured(tmp_path)
    config = replace(config, keep_last=1)
    times = iter([
        datetime(2026, 10, 30, hour, tzinfo=timezone.utc)
        for hour in (1, 2)
    ])
    original_run = scheduled.run_cycle

    def timed_run(**kwargs: object) -> dict[str, object]:
        return original_run(**kwargs, now=next(times))

    monkeypatch.setattr(scheduled, "run_cycle", timed_run)
    state = {"mounted": True}

    def mount_guard(_: scheduled.ScheduledBackupConfig) -> None:
        if not state["mounted"]:
            raise RuntimeError("Secondary mount disappeared")

    monkeypatch.setattr(scheduled, "require_independent_mount", mount_guard)
    scheduled.run_scheduled_cycle(config, lock_path=lock)
    first = config.primary / "athena-20261030T010000Z.db"
    assert first.is_file()

    original_copy = cycle.copy_verified_backup

    def copy_then_lose_mount(**kwargs: object) -> dict[str, object]:
        result = original_copy(**kwargs)
        state["mounted"] = False
        return result

    monkeypatch.setattr(cycle, "copy_verified_backup", copy_then_lose_mount)
    with pytest.raises(RuntimeError, match="mount disappeared"):
        scheduled.run_scheduled_cycle(config, lock_path=lock)

    # The new pair may exist, but a lost secondary mount must not authorize
    # deletion of the previously verified primary recovery point.
    assert first.is_file()
    assert len(list(config.primary.glob("athena-*.db"))) == 2

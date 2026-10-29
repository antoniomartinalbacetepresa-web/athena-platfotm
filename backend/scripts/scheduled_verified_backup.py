"""Linux scheduler entry point for a verified ATHENA backup and isolated restore.

Requires a separately mounted secondary filesystem; a local fallback directory
must never be accepted as off-site evidence. A mount is not proof of geography.
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from scripts.run_verified_backup_cycle import run_cycle


@dataclass(frozen=True)
class ScheduledBackupConfig:
    database: Path
    primary: Path
    secondary: Path
    keep_last: int
    secondary_keep_last: int | None = None


def load_config(environment: Mapping[str, str]) -> ScheduledBackupConfig:
    def required_path(key: str) -> Path:
        raw = environment.get(key, "")
        if not raw or raw != raw.strip() or "\x00" in raw:
            raise ValueError("Missing or invalid backup path configuration")
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError("Backup paths must be absolute")
        return path.resolve()

    database = required_path("ATHENA_BACKUP_DATABASE")
    primary = required_path("ATHENA_BACKUP_PRIMARY_DIRECTORY")
    secondary = required_path("ATHENA_BACKUP_SECONDARY_DIRECTORY")
    try:
        keep_last = int(environment.get("ATHENA_BACKUP_KEEP_LAST", "7"))
    except ValueError:
        raise ValueError("Invalid backup retention") from None
    if not 2 <= keep_last <= 365:
        raise ValueError("Backup retention must be between 2 and 365")
    secondary_raw = environment.get("ATHENA_BACKUP_SECONDARY_KEEP_LAST")
    secondary_keep_last = None
    if secondary_raw is not None:
        try:
            secondary_keep_last = int(secondary_raw)
        except ValueError:
            raise ValueError("Invalid secondary backup retention") from None
        if not keep_last <= secondary_keep_last <= 8760:
            raise ValueError("Secondary retention must be at least primary retention and at most 8760")
    if environment.get("ATHENA_BACKUP_ENCRYPTED_STORAGE_CONFIRMED") != "true":
        raise ValueError("Encrypted secondary storage operator confirmation required")
    if not database.is_file() or not primary.is_dir() or not secondary.is_dir():
        raise ValueError("Backup database and pre-provisioned directories must exist")
    return ScheduledBackupConfig(database, primary, secondary, keep_last, secondary_keep_last)


def require_independent_mount(config: ScheduledBackupConfig) -> None:
    """Reject a missing mount or same-filesystem fallback before any retention."""
    if (
        config.secondary == Path("/")
        or not config.secondary.is_mount()
        or config.secondary.stat().st_dev in {
            config.database.stat().st_dev, config.primary.stat().st_dev
        }
    ):
        raise RuntimeError("Independent secondary filesystem mount required")


def run_scheduled_cycle(
    config: ScheduledBackupConfig,
    *,
    lock_path: Path = Path("/run/athena-backup/cycle.lock"),
) -> dict[str, object]:
    if not lock_path.is_absolute() or not lock_path.parent.is_dir():
        raise ValueError("A pre-provisioned absolute scheduler lock directory is required")
    # flock prevents a delayed timer run and a manual invocation from racing
    # through backup retention. The unit owns the runtime lock directory.
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_independent_mount(config)
        result = run_cycle(
            database_path=config.database,
            backup_directory=config.primary,
            secondary_directory=config.secondary,
            keep_last=config.keep_last,
            secondary_keep_last=config.secondary_keep_last,
            prefix="athena-",
        )
        secondary = result.get("secondary")
        if (
            result.get("status") != "verified_backup_cycle_passed"
            or not isinstance(secondary, dict)
            or secondary.get("status") != "secondary_copy_verified"
            or not isinstance(secondary.get("restore_drill"), dict)
            or secondary["restore_drill"].get("schema_version", 0) <= 0
        ):
            raise RuntimeError("Secondary backup or isolated restore was not verified")
        require_independent_mount(config)
        return {
            "status": "scheduled_entrypoint_cycle_passed",
            "backupSha256": result["metadata"]["sha256"],
            "secondaryCopyAndRestoreVerified": True,
            "secondaryRetentionConfigured": config.secondary_keep_last is not None,
            "secondaryRetentionDeleted": len(result.get("secondary_retention", {}).get("deleted", [])) if isinstance(result.get("secondary_retention"), dict) else 0,
            "independentFilesystemMountChecked": True,
            "offsiteLocationVerified": False,
            "scheduledExecutionVerified": False,
            "productionRecoveryVerified": False,
        }


def main() -> int:
    try:
        config = load_config(os.environ)
    except (ValueError, OSError):
        print(json.dumps({"status": "blocked", "reason": "Backup configuration unavailable"}))
        return 2
    try:
        result = run_scheduled_cycle(config)
    except Exception:
        # No filesystem paths, exception text, credentials or customer data.
        print(json.dumps({"status": "failed", "reason": "Verified backup cycle did not pass"}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

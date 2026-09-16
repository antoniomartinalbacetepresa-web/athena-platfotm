"""Verify an ATHENA database backup by restoring it into an isolated database.

This command is deliberately destructive only to the temporary verification target. It
never restores over the configured production database and exits non-zero whenever a
backup cannot be proven restorable.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.database_backup_service import DatabaseBackupService


def _verify_sqlite_backup(source: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Backup does not exist: {source}")
    with tempfile.TemporaryDirectory(prefix="athena-recovery-") as directory:
        restored = Path(directory) / "restored.db"
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        target_connection = sqlite3.connect(restored)
        try:
            source_connection.backup(target_connection)
            integrity = target_connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or str(integrity[0]).lower() != "ok":
                raise RuntimeError(f"Restored database integrity check failed: {integrity}")
            target_connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        finally:
            target_connection.close()
            source_connection.close()


def verify_backup(backup_path: Path, *, database_url: str | None = None) -> None:
    configured_url = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if configured_url.startswith("sqlite") or backup_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        _verify_sqlite_backup(backup_path)
        return
    raise RuntimeError(
        "Recovery verification is not implemented for this database backend; refusing to report success"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify that an ATHENA backup is actually restorable")
    parser.add_argument("backup", type=Path, help="Backup artifact to verify")
    args = parser.parse_args(argv)
    try:
        verify_backup(args.backup)
    except Exception as exc:
        print(f"RECOVERY VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"RECOVERY VERIFIED: {args.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

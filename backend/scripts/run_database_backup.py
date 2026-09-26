from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService


def _required_directory() -> Path:
    raw = (os.getenv("ATHENA_BACKUP_DIRECTORY") or "").strip()
    if not raw:
        raise RuntimeError("ATHENA_BACKUP_DIRECTORY no está configurado.")
    return Path(raw).expanduser().resolve()


def _required_retention() -> int:
    raw = (os.getenv("ATHENA_BACKUP_KEEP_LAST") or "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("ATHENA_BACKUP_KEEP_LAST no es válido.") from exc
    if value < 1:
        raise RuntimeError("ATHENA_BACKUP_KEEP_LAST debe ser positivo.")
    return value


def run_backup() -> dict[str, object]:
    database = AthenaDatabase()
    backup_directory = _required_directory()
    live_directory = database.database_path.expanduser().resolve().parent
    if backup_directory == live_directory:
        raise RuntimeError("El backup no puede compartir directorio con la base activa.")

    service = DatabaseBackupService(database)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_directory / f"athena-{timestamp}.db"
    metadata = service.create_backup(backup_path)
    verified = service.verify_backup(backup_path)
    if verified != metadata:
        raise RuntimeError("La verificación del backup no coincide con su creación.")

    retention = service.apply_retention(
        backup_directory,
        keep_last=_required_retention(),
    )
    return {
        "status": "ok",
        "backup": backup_path.name,
        "schemaVersion": metadata.schema_version,
        "sizeBytes": metadata.size_bytes,
        "sha256Verified": True,
        "retention": retention.to_dict(),
        "policy": {
            "scheduledExecutionVerified": False,
            "offsiteCopyVerified": False,
            "restoreDrillOperationallyVerified": False,
        },
    }


def main() -> int:
    print(json.dumps(run_backup(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

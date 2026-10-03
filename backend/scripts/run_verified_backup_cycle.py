from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta un ciclo operativo de backup ATHENA: crea, verifica, "
            "prueba restauración y aplica retención fail-closed."
        )
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--keep-last", type=int, default=7)
    parser.add_argument("--prefix", default="athena-")
    return parser


def run_cycle(
    *,
    database_path: Path | None,
    backup_directory: Path,
    keep_last: int,
    prefix: str,
    now: datetime | None = None,
) -> dict[str, object]:
    if keep_last < 1:
        raise ValueError("La retención debe conservar al menos un backup.")
    if not prefix or Path(prefix).name != prefix:
        raise ValueError("El prefijo de backup no es válido.")

    database = AthenaDatabase(database_path)
    service = DatabaseBackupService(database)
    backup_directory.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backup_path = backup_directory / f"{prefix}{timestamp:%Y%m%dT%H%M%SZ}.db"

    created = service.create_backup(backup_path)
    verified = service.verify_backup(backup_path)
    if verified != created:
        raise RuntimeError("La verificación no conserva los metadatos del backup creado.")

    drill = service.run_restore_drill(backup_path)
    retention = service.apply_retention(
        backup_directory,
        keep_last=keep_last,
        filename_prefix=prefix,
    )

    return {
        "status": "verified_backup_cycle_passed",
        "backup": str(backup_path),
        "manifest": str(service.manifest_path_for(backup_path)),
        "metadata": verified.to_dict(),
        "restore_drill": drill.to_dict(),
        "retention": retention.to_dict(),
        "policy": {
            "integrityVerified": True,
            "restoreDrillVerified": True,
            "offsiteBackupVerified": False,
            "scheduledExecutionVerified": False,
            "productionRecoveryVerified": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_cycle(
        database_path=args.database,
        backup_directory=args.directory,
        keep_last=args.keep_last,
        prefix=args.prefix,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService
from scripts.copy_verified_backup_secondary import copy_verified_backup


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
    parser.add_argument("--secondary-directory", type=Path, default=None)
    parser.add_argument("--offsite-attestation", action="store_true")
    return parser


def run_cycle(
    *,
    database_path: Path | None,
    backup_directory: Path,
    keep_last: int,
    prefix: str,
    now: datetime | None = None,
    secondary_directory: Path | None = None,
    offsite_attested: bool = False,
) -> dict[str, object]:
    if keep_last < 1:
        raise ValueError("La retención debe conservar al menos un backup.")
    if not prefix or Path(prefix).name != prefix:
        raise ValueError("El prefijo de backup no es válido.")
    if offsite_attested and secondary_directory is None:
        raise ValueError("La declaración off-site requiere destino secundario.")

    # Reject unsafe layouts before creating any backup or applying retention.
    # A backup stored beside the live SQLite file can be mistaken for live
    # database state and shares its failure boundary.
    database = AthenaDatabase(database_path)
    live_root = database.database_path.expanduser().resolve().parent
    primary_root = backup_directory.expanduser().resolve()
    if (
        primary_root == live_root
        or primary_root in live_root.parents
        or live_root in primary_root.parents
    ):
        raise ValueError("El backup primario no puede compartir el árbol de directorios con la base activa.")
    if secondary_directory is not None:
        secondary_root = secondary_directory.expanduser().resolve()
        if (
            secondary_root == live_root
            or secondary_root in live_root.parents
            or live_root in secondary_root.parents
        ):
            raise ValueError("El destino secundario no puede compartir el árbol de directorios con la base activa.")
        if (
            primary_root == secondary_root
            or primary_root in secondary_root.parents
            or secondary_root in primary_root.parents
        ):
            raise ValueError("El destino secundario debe ser independiente del directorio primario.")

    service = DatabaseBackupService(database)
    backup_directory.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backup_path = backup_directory / f"{prefix}{timestamp:%Y%m%dT%H%M%SZ}.db"

    created = service.create_backup(backup_path)
    verified = service.verify_backup(backup_path)
    if verified != created:
        raise RuntimeError("La verificación no conserva los metadatos del backup creado.")

    drill = service.run_restore_drill(backup_path)

    # Retention must run AFTER secondary verification and its isolated restore.
    # On any secondary failure, older primary recovery points remain intact.
    secondary = None
    if secondary_directory is not None:
        secondary = copy_verified_backup(
            backup_path=backup_path,
            manifest_path=service.manifest_path_for(backup_path),
            destination_directory=secondary_directory,
            offsite_attested=offsite_attested,
        )
    retention = service.apply_retention(
        backup_directory,
        keep_last=keep_last,
        filename_prefix=prefix,
    )

    return {
        "status": "verified_backup_cycle_passed",
        "secondary": secondary,
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
        secondary_directory=args.secondary_directory,
        offsite_attested=args.offsite_attestation,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

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
    parser.add_argument("--secondary-keep-last", type=int, default=None,
                        help="Opt-in independent secondary retention; must be >= primary retention")
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
    secondary_keep_last: int | None = None,
    offsite_attested: bool = False,
    secondary_guard: Callable[[], None] | None = None,
) -> dict[str, object]:
    if keep_last < 1:
        raise ValueError("La retención debe conservar al menos un backup.")
    DatabaseBackupService.validate_filename_prefix(prefix)
    if offsite_attested and secondary_directory is None:
        raise ValueError("La declaración off-site requiere destino secundario.")
    if secondary_guard is not None and secondary_directory is None:
        raise ValueError("A secondary guard requires a secondary destination.")
    if secondary_keep_last is not None:
        if secondary_directory is None:
            raise ValueError("La retención secundaria requiere destino secundario.")
        if not keep_last <= secondary_keep_last <= 8760:
            raise ValueError("La retención secundaria debe conservar al menos la primaria y no superar 8760 copias.")

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
    secondary_retention = None
    if secondary_directory is not None:
        # The scheduled entrypoint pins the mount identity across the cycle.
        # Refuse a vanished or replaced secondary mount before copying.
        if secondary_guard is not None:
            secondary_guard()
        secondary = copy_verified_backup(
            backup_path=backup_path,
            manifest_path=service.manifest_path_for(backup_path),
            destination_directory=secondary_directory,
            offsite_attested=offsite_attested,
        )
        # A mount may disappear during copy/restore. Never prune an older
        # recovery point until the scheduler has rechecked its identity.
        if secondary_guard is not None:
            secondary_guard()
        # Prune only verified managed secondary copies. If verification or
        # secondary retention fails, preserve every older primary recovery point.
        if secondary_keep_last is not None:
            secondary_retention = service.apply_retention(
                secondary_directory,
                keep_last=secondary_keep_last,
                filename_prefix=prefix,
            )
    # Recheck after secondary retention as well: the primary is the last
    # recovery boundary and must survive a secondary mount transition.
    if secondary_guard is not None:
        secondary_guard()
    retention = service.apply_retention(
        backup_directory,
        keep_last=keep_last,
        filename_prefix=prefix,
    )

    return {
        "status": "verified_backup_cycle_passed",
        "secondary": secondary,
        "secondary_retention": (
            secondary_retention.to_dict() if secondary_retention is not None else None
        ),
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
        secondary_keep_last=args.secondary_keep_last,
        offsite_attested=args.offsite_attestation,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

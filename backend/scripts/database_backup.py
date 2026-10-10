from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backup y recuperación verificada de la base SQLite de ATHENA TYCHE."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "Ruta de la base activa. Si se omite se usa ATHENA_DATABASE_PATH o el valor por defecto."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    backup_parser = subparsers.add_parser(
        "backup",
        help="Crea una instantánea SQLite consistente y su manifiesto de integridad.",
    )
    backup_parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verifica checksum, integridad SQLite y versión de esquema.",
    )
    verify_parser.add_argument(
        "--backup",
        required=True,
        type=Path,
    )

    restore_parser = subparsers.add_parser(
        "restore",
        help=(
            "Restaura un backup verificado a una ruta nueva; nunca sobrescribe la base activa."
        ),
    )
    restore_parser.add_argument(
        "--backup",
        required=True,
        type=Path,
    )
    restore_parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    drill_parser = subparsers.add_parser(
        "drill",
        help=(
            "Ejecuta un restore drill efímero: verifica, restaura, valida y limpia sin tocar la base activa."
        ),
    )
    drill_parser.add_argument(
        "--backup",
        required=True,
        type=Path,
    )
    drill_parser.add_argument(
        "--working-directory",
        type=Path,
        default=None,
        help=(
            "Directorio temporal opcional para el drill. No puede ser el directorio de la base activa."
        ),
    )

    retention_parser = subparsers.add_parser(
        "retain",
        help=(
            "Aplica retención fail-closed: verifica todos los backups gestionados antes de borrar los antiguos."
        ),
    )
    retention_parser.add_argument(
        "--directory",
        required=True,
        type=Path,
    )
    retention_parser.add_argument(
        "--keep-last",
        required=True,
        type=int,
    )
    retention_parser.add_argument(
        "--prefix",
        default="athena-",
        help="Prefijo de los backups gestionados. Por defecto: athena-",
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = build_parser().parse_args(
        argv
    )

    database = AthenaDatabase(
        args.database
    )
    service = DatabaseBackupService(
        database
    )

    if args.command == "backup":
        metadata = service.create_backup(
            args.output
        )
        result = {
            "status": "backup_created",
            "backup": str(args.output),
            "manifest": str(
                service.manifest_path_for(
                    args.output
                )
            ),
            "metadata": metadata.to_dict(),
        }
    elif args.command == "verify":
        metadata = service.verify_backup(
            args.backup
        )
        result = {
            "status": "backup_verified",
            "backup": str(args.backup),
            "metadata": metadata.to_dict(),
        }
    elif args.command == "restore":
        metadata = service.restore_backup(
            args.backup,
            args.output,
        )
        result = {
            "status": "backup_restored",
            "backup": str(args.backup),
            "restored_database": str(
                args.output
            ),
            "metadata": metadata.to_dict(),
        }
    elif args.command == "drill":
        drill = service.run_restore_drill(
            args.backup,
            working_directory=args.working_directory,
        )
        result = {
            "status": "restore_drill_passed",
            "drill": drill.to_dict(),
        }
    elif args.command == "retain":
        retention = service.apply_retention(
            args.directory,
            keep_last=args.keep_last,
            filename_prefix=args.prefix,
        )
        result = {
            "status": "backup_retention_applied",
            "directory": str(args.directory),
            "keep_last": args.keep_last,
            "prefix": args.prefix,
            "retention": retention.to_dict(),
        }
    else:
        raise RuntimeError(
            "Comando de backup no soportado."
        )

    print(
        json.dumps(
            result,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )

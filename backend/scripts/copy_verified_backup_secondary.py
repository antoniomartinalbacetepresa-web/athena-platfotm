from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copia un backup ATHENA ya verificado a un destino secundario y "
            "verifica por SHA-256 que la copia es idéntica."
        )
    )
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--offsite-attestation",
        action="store_true",
        help=(
            "Registra únicamente la declaración del operador de que el destino es off-site; "
            "no la convierte en verificación operacional."
        ),
    )
    return parser


def copy_verified_backup(
    *,
    backup_path: Path,
    manifest_path: Path,
    destination_directory: Path,
    offsite_attested: bool = False,
) -> dict[str, object]:
    source = backup_path.expanduser().resolve()
    manifest = manifest_path.expanduser().resolve()
    destination = destination_directory.expanduser().resolve()

    if not source.is_file() or not manifest.is_file():
        raise FileNotFoundError("El backup y su manifiesto deben existir.")
    # Resolve symlink aliases and reject both directions of nesting. A
    # secondary directory inside (or containing) the primary is not an
    # independent recovery boundary, even when the paths differ.
    primary_directory = source.parent
    if (
        destination == primary_directory
        or primary_directory in destination.parents
        or destination in primary_directory.parents
    ):
        raise ValueError("El destino secundario debe ser independiente del directorio primario.")

    # A matching SHA alone does not prove that this is an ATHENA backup:
    # enforce the canonical adjacent manifest, schema and SQLite integrity.
    if manifest != DatabaseBackupService.manifest_path_for(source).resolve():
        raise ValueError("El manifiesto debe corresponder al backup indicado.")

    # Preserve the public CLI contract for a malformed digest while the
    # full verifier below checks all manifest fields and SQLite integrity.
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    expected_sha = str(payload.get("sha256") or "").strip().lower()
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("El manifiesto no contiene un SHA-256 válido.")

    with tempfile.TemporaryDirectory(prefix="athena-secondary-verify-") as temp_dir:
        verifier_root = Path(temp_dir)
        verifier = DatabaseBackupService(
            AthenaDatabase(verifier_root / "verifier-source.db")
        )
        metadata = verifier.verify_backup(source)

        destination.mkdir(parents=True, exist_ok=True)
        copied_backup = destination / source.name
        copied_manifest = destination / manifest.name
        if (copied_backup.exists() or copied_backup.is_symlink()
                or copied_manifest.exists() or copied_manifest.is_symlink()):
            raise FileExistsError("El destino ya contiene este backup o manifiesto.")

        # Exclusive creation prevents overwriting pre-existing evidence,
        # including symlinks. The manifest is published only after the DB.
        created: list[Path] = []
        try:
            with source.open("rb") as reader, copied_backup.open("xb") as writer:
                created.append(copied_backup)
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
            with manifest.open("rb") as reader, copied_manifest.open("xb") as writer:
                created.append(copied_manifest)
                shutil.copyfileobj(reader, writer, length=1024 * 1024)

            copied_metadata = verifier.verify_backup(copied_backup)
            if copied_metadata != metadata:
                raise RuntimeError("La copia secundaria no conserva los metadatos.")
            drill = verifier.run_restore_drill(
                copied_backup,
                working_directory=verifier_root / "restore",
            )
        except Exception:
            for created_path in reversed(created):
                created_path.unlink(missing_ok=True)
            raise

    return {
        "status": "secondary_copy_verified",
        "backup": str(copied_backup),
        "manifest": str(copied_manifest),
        "sha256": metadata.sha256,
        "restore_drill": drill.to_dict(),
        "policy": {
            "secondaryCopyVerified": True,
            "offsiteLocationOperatorAttested": offsite_attested is True,
            "offsiteLocationVerified": False,
            "scheduledExecutionVerified": False,
            "productionRecoveryVerified": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = copy_verified_backup(
        backup_path=args.backup,
        manifest_path=args.manifest,
        destination_directory=args.destination,
        offsite_attested=args.offsite_attestation,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

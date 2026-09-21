from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Sequence


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
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_verified_backup(
    *,
    backup_path: Path,
    manifest_path: Path,
    destination_directory: Path,
) -> dict[str, object]:
    source = backup_path.expanduser().resolve()
    manifest = manifest_path.expanduser().resolve()
    destination = destination_directory.expanduser().resolve()

    if not source.is_file() or not manifest.is_file():
        raise FileNotFoundError("El backup y su manifiesto deben existir.")
    if destination == source.parent:
        raise ValueError("El destino secundario no puede ser el directorio del backup primario.")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    expected_sha = str(payload.get("sha256") or "").strip().lower()
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("El manifiesto no contiene un SHA-256 válido.")

    source_sha = _sha256(source)
    if source_sha != expected_sha:
        raise RuntimeError("El backup primario no coincide con su manifiesto.")

    destination.mkdir(parents=True, exist_ok=True)
    copied_backup = destination / source.name
    copied_manifest = destination / manifest.name
    if copied_backup.exists() or copied_manifest.exists():
        raise FileExistsError("El destino ya contiene este backup o manifiesto.")

    shutil.copy2(source, copied_backup)
    shutil.copy2(manifest, copied_manifest)

    copied_sha = _sha256(copied_backup)
    if copied_sha != expected_sha:
        copied_backup.unlink(missing_ok=True)
        copied_manifest.unlink(missing_ok=True)
        raise RuntimeError("La copia secundaria no supera la verificación SHA-256.")

    return {
        "status": "secondary_copy_verified",
        "backup": str(copied_backup),
        "manifest": str(copied_manifest),
        "sha256": expected_sha,
        "policy": {
            "secondaryCopyVerified": True,
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
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

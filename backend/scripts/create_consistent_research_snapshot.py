"""Export a consistent, read-only-source SQLite research snapshot for offline audit.

An operator must explicitly authorize copying a database containing sensitive data.
The SQLite online backup API includes committed WAL transactions; a raw .db copy
may not. No migration, inference, network request, or investment order occurs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _no_sidecars(path: Path) -> bool:
    return not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def export_snapshot(source: Path, destination: Path, *, acknowledge_sensitive_copy: bool = False) -> dict[str, object]:
    """Create a new checkpointed snapshot; never overwrite a pre-existing file."""
    if not acknowledge_sensitive_copy:
        raise ValueError("Se requiere autorización explícita para copiar datos sensibles.")
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().absolute()
    if not source.is_file() or not destination.parent.is_dir():
        raise ValueError("Origen o directorio de destino inválido.")
    if destination.exists() or destination.is_symlink():
        raise ValueError("El snapshot de destino ya existe; no se sobrescribe.")
    if source == destination.resolve():
        raise ValueError("Origen y destino deben ser distintos.")

    temporary: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".athena-research-", suffix=".db", dir=destination.parent)
        temporary = Path(temp_name)
        os.chmod(temporary, 0o600)
        os.close(fd)
        # mode=ro is important: never allow SQLite to create/migrate the live DB.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=15)) as live:
            with closing(sqlite3.connect(temporary)) as copy:
                live.backup(copy, pages=256, sleep=0.05)
                # The backup may inherit WAL journal mode. Convert the *copy* to
                # a single-file checkpointed database before hashing it.
                mode = copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                if mode.lower() != "delete":
                    raise ValueError("No se pudo cerrar el journal del snapshot.")
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("El snapshot no supera SQLite integrity_check.")
        if not _no_sidecars(temporary):
            raise ValueError("El snapshot conserva journals auxiliares SQLite.")
        digest = _digest(temporary)
        size = temporary.stat().st_size
        # Hard-link publication is atomic and fails if destination exists,
        # including on concurrent invocations. Both paths are on one volume.
        os.link(temporary, destination)
        if not _no_sidecars(destination) or _digest(destination) != digest:
            destination.unlink(missing_ok=True)
            raise ValueError("La copia publicada no conserva su integridad.")
        return {
            "status": "consistent_snapshot_created",
            "snapshotSha256": digest,
            "sizeBytes": size,
            "sqliteIntegrityCheck": "ok",
            "independentCustodyVerified": False,
            "realMarketEvidenceVerified": False,
            "productionEligible": False,
            "automaticTrading": False,
        }
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(temporary) + suffix).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--acknowledge-sensitive-copy", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = export_snapshot(args.source, args.destination, acknowledge_sensitive_copy=args.acknowledge_sensitive_copy)
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        # Never print paths, SQL rows, credentials or exception messages.
        print(json.dumps({"status": "blocked", "reason": type(exc).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

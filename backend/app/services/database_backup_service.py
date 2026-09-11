from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class DatabaseBackupMetadata:
    format_version: int
    created_at_utc: str
    schema_version: int
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "created_at_utc": self.created_at_utc,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


class DatabaseBackupService:
    FORMAT_VERSION = 1

    def __init__(
        self,
        database: AthenaDatabase,
    ) -> None:
        self._database = database

    def create_backup(
        self,
        backup_path: str | Path,
    ) -> DatabaseBackupMetadata:
        source_path = self._database.database_path
        destination = Path(backup_path)

        if not source_path.exists():
            raise FileNotFoundError(
                "La base de datos de ATHENA no existe."
            )

        if self._same_path(
            source_path,
            destination,
        ):
            raise ValueError(
                "El backup no puede sobrescribir la base de datos activa."
            )

        manifest_path = self.manifest_path_for(
            destination
        )

        if destination.exists() or manifest_path.exists():
            raise FileExistsError(
                "El destino de backup ya existe; ATHENA no lo sobrescribe."
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_backup = destination.with_name(
            f".{destination.name}.tmp"
        )
        temporary_manifest = manifest_path.with_name(
            f".{manifest_path.name}.tmp"
        )

        self._remove_if_exists(
            temporary_backup
        )
        self._remove_if_exists(
            temporary_manifest
        )

        try:
            with self._database.connect() as source:
                target = sqlite3.connect(
                    temporary_backup
                )
                try:
                    source.backup(
                        target
                    )
                    target.commit()
                finally:
                    target.close()

            schema_version = self._validate_database_file(
                temporary_backup
            )
            digest = self._sha256(
                temporary_backup
            )
            metadata = DatabaseBackupMetadata(
                format_version=self.FORMAT_VERSION,
                created_at_utc=datetime.now(
                    timezone.utc
                ).isoformat(),
                schema_version=schema_version,
                sha256=digest,
                size_bytes=temporary_backup.stat().st_size,
            )

            temporary_manifest.write_text(
                json.dumps(
                    metadata.to_dict(),
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

            os.replace(
                temporary_backup,
                destination,
            )
            os.replace(
                temporary_manifest,
                manifest_path,
            )

            return metadata
        except Exception:
            self._remove_if_exists(
                temporary_backup
            )
            self._remove_if_exists(
                temporary_manifest
            )
            raise

    def verify_backup(
        self,
        backup_path: str | Path,
    ) -> DatabaseBackupMetadata:
        source = Path(backup_path)
        manifest_path = self.manifest_path_for(
            source
        )

        if not source.is_file():
            raise FileNotFoundError(
                "No existe el fichero de backup."
            )

        if not manifest_path.is_file():
            raise FileNotFoundError(
                "El backup no tiene manifiesto de integridad."
            )

        metadata = self._read_manifest(
            manifest_path
        )

        if metadata.format_version != self.FORMAT_VERSION:
            raise RuntimeError(
                "El formato del backup no es compatible con esta versión de ATHENA."
            )

        actual_size = source.stat().st_size
        if actual_size != metadata.size_bytes:
            raise RuntimeError(
                "El tamaño del backup no coincide con su manifiesto."
            )

        actual_digest = self._sha256(
            source
        )
        if actual_digest != metadata.sha256:
            raise RuntimeError(
                "El checksum SHA-256 del backup no coincide."
            )

        schema_version = self._validate_database_file(
            source
        )
        if schema_version != metadata.schema_version:
            raise RuntimeError(
                "La versión de esquema del backup no coincide con su manifiesto."
            )

        return metadata

    def restore_backup(
        self,
        backup_path: str | Path,
        destination_path: str | Path,
    ) -> DatabaseBackupMetadata:
        source = Path(backup_path)
        destination = Path(destination_path)

        metadata = self.verify_backup(
            source
        )

        if self._same_path(
            source,
            destination,
        ):
            raise ValueError(
                "El destino restaurado debe ser distinto del backup."
            )

        if self._same_path(
            self._database.database_path,
            destination,
        ):
            raise ValueError(
                "La restauración en caliente sobre la base activa está bloqueada."
            )

        if destination.exists():
            raise FileExistsError(
                "El destino de restauración ya existe; ATHENA no lo sobrescribe."
            )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_destination = destination.with_name(
            f".{destination.name}.tmp"
        )
        self._remove_if_exists(
            temporary_destination
        )

        try:
            source_connection = sqlite3.connect(
                f"file:{source.as_posix()}?mode=ro",
                uri=True,
            )
            target_connection = sqlite3.connect(
                temporary_destination
            )
            try:
                source_connection.backup(
                    target_connection
                )
                target_connection.commit()
            finally:
                target_connection.close()
                source_connection.close()

            restored_schema = self._validate_database_file(
                temporary_destination
            )
            if restored_schema != metadata.schema_version:
                raise RuntimeError(
                    "La restauración no conserva la versión de esquema esperada."
                )

            os.replace(
                temporary_destination,
                destination,
            )

            return metadata
        except Exception:
            self._remove_if_exists(
                temporary_destination
            )
            raise

    @staticmethod
    def manifest_path_for(
        backup_path: str | Path,
    ) -> Path:
        path = Path(backup_path)
        return path.with_name(
            f"{path.name}.manifest.json"
        )

    def _validate_database_file(
        self,
        database_path: Path,
    ) -> int:
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            integrity_rows = connection.execute(
                "PRAGMA integrity_check"
            ).fetchall()
            integrity_messages = [
                str(row[0])
                for row in integrity_rows
            ]
            if integrity_messages != ["ok"]:
                raise RuntimeError(
                    "El backup no supera PRAGMA integrity_check."
                )

            row = connection.execute(
                """
                SELECT value
                FROM schema_metadata
                WHERE key = 'schema_version'
                """
            ).fetchone()
            if row is None:
                raise RuntimeError(
                    "El backup no contiene versión de esquema ATHENA."
                )

            try:
                schema_version = int(
                    row["value"]
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "La versión de esquema del backup no es válida."
                ) from exc

            if schema_version > AthenaDatabase.SCHEMA_VERSION:
                raise RuntimeError(
                    "El backup usa un esquema más reciente que esta versión de ATHENA."
                )

            return schema_version
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "El fichero no es una base SQLite ATHENA válida."
            ) from exc
        finally:
            connection.close()

    def _read_manifest(
        self,
        manifest_path: Path,
    ) -> DatabaseBackupMetadata:
        try:
            raw = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
            if not isinstance(raw, dict):
                raise TypeError

            return DatabaseBackupMetadata(
                format_version=int(
                    raw["format_version"]
                ),
                created_at_utc=str(
                    raw["created_at_utc"]
                ),
                schema_version=int(
                    raw["schema_version"]
                ),
                sha256=str(
                    raw["sha256"]
                ),
                size_bytes=int(
                    raw["size_bytes"]
                ),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "El manifiesto del backup no es válido."
            ) from exc

    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(
                    chunk
                )
        return digest.hexdigest()

    @staticmethod
    def _same_path(
        left: Path,
        right: Path,
    ) -> bool:
        return left.expanduser().resolve() == right.expanduser().resolve()

    @staticmethod
    def _remove_if_exists(
        path: Path,
    ) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

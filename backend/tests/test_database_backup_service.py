from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService


def _seed_database(
    database: AthenaDatabase,
) -> None:
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS backup_probe (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO backup_probe (
                id,
                value
            )
            VALUES (?, ?)
            """,
            (1, "persisted-before-backup"),
        )


def test_create_verify_and_restore_backup(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "live" / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backups" / "athena.db"

    metadata = service.create_backup(
        backup_path
    )

    assert backup_path.is_file()
    assert metadata.schema_version == AthenaDatabase.SCHEMA_VERSION
    assert metadata.size_bytes == backup_path.stat().st_size
    assert len(metadata.sha256) == 64

    manifest_path = service.manifest_path_for(
        backup_path
    )
    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    assert manifest["sha256"] == metadata.sha256

    verified = service.verify_backup(
        backup_path
    )
    assert verified == metadata

    restored_path = tmp_path / "restore" / "athena.db"
    restored = service.restore_backup(
        backup_path,
        restored_path,
    )
    assert restored == metadata

    connection = sqlite3.connect(
        restored_path
    )
    try:
        row = connection.execute(
            """
            SELECT value
            FROM backup_probe
            WHERE id = 1
            """
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == "persisted-before-backup"


def test_backup_is_consistent_while_database_uses_wal(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    with database.connect() as connection:
        mode = connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()
        assert mode is not None
        assert str(mode[0]).lower() == "wal"

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backup.db"
    service.create_backup(
        backup_path
    )

    backup_connection = sqlite3.connect(
        backup_path
    )
    try:
        row = backup_connection.execute(
            """
            SELECT value
            FROM backup_probe
            WHERE id = 1
            """
        ).fetchone()
    finally:
        backup_connection.close()

    assert row is not None
    assert row[0] == "persisted-before-backup"


def test_verify_rejects_tampered_backup(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backup.db"
    service.create_backup(
        backup_path
    )

    with backup_path.open("ab") as handle:
        handle.write(
            b"tampered"
        )

    with pytest.raises(
        RuntimeError,
        match="tamaño|checksum",
    ):
        service.verify_backup(
            backup_path
        )


def test_verify_rejects_tampered_manifest(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backup.db"
    service.create_backup(
        backup_path
    )

    manifest_path = service.manifest_path_for(
        backup_path
    )
    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )
    manifest["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="checksum",
    ):
        service.verify_backup(
            backup_path
        )


def test_create_backup_never_overwrites_existing_destination(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backup.db"
    backup_path.write_bytes(
        b"do-not-overwrite"
    )

    with pytest.raises(
        FileExistsError,
    ):
        service.create_backup(
            backup_path
        )

    assert backup_path.read_bytes() == b"do-not-overwrite"


def test_restore_refuses_active_database_and_existing_destination(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )
    backup_path = tmp_path / "backup.db"
    service.create_backup(
        backup_path
    )

    with pytest.raises(
        ValueError,
        match="base activa",
    ):
        service.restore_backup(
            backup_path,
            database.database_path,
        )

    existing_destination = tmp_path / "existing.db"
    existing_destination.write_bytes(
        b"keep-me"
    )

    with pytest.raises(
        FileExistsError,
    ):
        service.restore_backup(
            backup_path,
            existing_destination,
        )

    assert existing_destination.read_bytes() == b"keep-me"


def test_backup_rejects_source_as_destination(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "athena.db"
    )
    _seed_database(
        database
    )

    service = DatabaseBackupService(
        database
    )

    with pytest.raises(
        ValueError,
        match="base de datos activa",
    ):
        service.create_backup(
            database.database_path
        )

from __future__ import annotations

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
            CREATE TABLE IF NOT EXISTS restore_drill_probe (
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO restore_drill_probe (value)
            VALUES ('restore-drill-persisted')
            """
        )


def test_restore_drill_restores_validates_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "live" / "athena.db"
    )
    _seed_database(database)
    service = DatabaseBackupService(database)
    backup_path = tmp_path / "backups" / "athena-001.db"
    service.create_backup(backup_path)

    working_directory = tmp_path / "drills"
    result = service.run_restore_drill(
        backup_path,
        working_directory=working_directory,
    )

    assert result.backup == str(backup_path)
    assert result.schema_version == AthenaDatabase.SCHEMA_VERSION
    assert result.verified_at_utc.endswith("+00:00")
    assert working_directory.is_dir()
    assert list(working_directory.iterdir()) == []
    assert database.database_path.is_file()


def test_restore_drill_rejects_tampered_backup_without_leaving_workspace_artifacts(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "live" / "athena.db"
    )
    _seed_database(database)
    service = DatabaseBackupService(database)
    backup_path = tmp_path / "backups" / "athena-001.db"
    service.create_backup(backup_path)

    with backup_path.open("ab") as handle:
        handle.write(b"tampered")

    working_directory = tmp_path / "drills"
    with pytest.raises(RuntimeError, match="tamaño|checksum"):
        service.run_restore_drill(
            backup_path,
            working_directory=working_directory,
        )

    assert not working_directory.exists()


def test_restore_drill_refuses_active_database_directory_as_workspace(
    tmp_path: Path,
) -> None:
    database = AthenaDatabase(
        tmp_path / "live" / "athena.db"
    )
    _seed_database(database)
    service = DatabaseBackupService(database)
    backup_path = tmp_path / "backups" / "athena-001.db"
    service.create_backup(backup_path)

    with pytest.raises(
        ValueError,
        match="directorio de la base activa",
    ):
        service.run_restore_drill(
            backup_path,
            working_directory=database.database_path.parent,
        )

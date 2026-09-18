from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService
from scripts.verify_backup_recovery import main, verify_backup


def _managed_backup(tmp_path: Path) -> Path:
    database = AthenaDatabase(tmp_path / "source.db")
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS recovery_evidence "
            "(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO recovery_evidence(value) VALUES (?)",
            ("athena",),
        )
    backup = tmp_path / "athena-backup.db"
    DatabaseBackupService(database).create_backup(backup)
    return backup


def test_verify_backup_restores_managed_sqlite_into_isolated_database(
    tmp_path: Path,
) -> None:
    backup = _managed_backup(tmp_path)

    verify_backup(backup, database_url="sqlite:///production.db")

    # Recovery verification is read-only with respect to the backup artifact.
    metadata = DatabaseBackupService(
        AthenaDatabase(tmp_path / "unused.db")
    ).verify_backup(backup)
    assert metadata.schema_version == AthenaDatabase.SCHEMA_VERSION


def test_verify_backup_rejects_sqlite_without_athena_manifest(tmp_path: Path) -> None:
    backup = _managed_backup(tmp_path)
    DatabaseBackupService.manifest_path_for(backup).unlink()

    with pytest.raises(RuntimeError, match="manifest is missing"):
        verify_backup(backup, database_url="sqlite:///production.db")


def test_verify_backup_rejects_tampered_managed_sqlite(tmp_path: Path) -> None:
    backup = _managed_backup(tmp_path)
    with backup.open("ab") as handle:
        handle.write(b"tampered-after-manifest")

    with pytest.raises(RuntimeError, match="tamaño|checksum|integrity"):
        verify_backup(backup, database_url="sqlite:///production.db")


def test_verify_backup_fails_closed_for_unimplemented_backend(tmp_path: Path) -> None:
    backup = tmp_path / "athena.dump"
    backup.write_text("placeholder")

    with pytest.raises(RuntimeError, match="not implemented"):
        verify_backup(
            backup,
            database_url="postgresql://example.invalid/athena",
        )


def test_cli_returns_nonzero_for_missing_backup(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.db")]) == 1
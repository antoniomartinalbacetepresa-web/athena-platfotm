from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.database_backup_service import DatabaseBackupService
from scripts import verify_backup_recovery as recovery_script
from scripts.verify_backup_recovery import main, verify_backup


def _managed_backup(tmp_path: Path) -> Path:
    database = AthenaDatabase(tmp_path / "source.db")
    database.initialize()
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


def test_verify_backup_leaves_external_backup_directory_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_directory = tmp_path / "external-read-only-store"
    external_directory.mkdir()
    backup = _managed_backup(external_directory)

    class RequireIsolatedVerifier(DatabaseBackupService):
        def __init__(self, database: AthenaDatabase) -> None:
            # This must fail against the previous implementation, which bound
            # the verifier to a fake database path beside the backup artifact.
            assert database.database_path.parent.resolve() != external_directory.resolve()
            super().__init__(database)

    monkeypatch.setattr(recovery_script, "DatabaseBackupService", RequireIsolatedVerifier)
    original_files = {
        entry.name: entry.read_bytes()
        for entry in external_directory.iterdir()
        if entry.is_file()
    }

    verify_backup(backup, database_url="sqlite:///production.db")

    # Verification and restore drill must never create temporary database or
    # journal files beside an immutable/off-site backup and its manifest.
    assert {
        entry.name: entry.read_bytes()
        for entry in external_directory.iterdir()
        if entry.is_file()
    } == original_files
    assert not (external_directory / ".athena-recovery-verifier-source.db").exists()


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
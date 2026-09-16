import sqlite3
from pathlib import Path

import pytest

from scripts.verify_backup_recovery import main, verify_backup


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence(value) VALUES ('athena')")
        connection.commit()
    finally:
        connection.close()


def test_verify_backup_restores_sqlite_into_isolated_database(tmp_path: Path) -> None:
    backup = tmp_path / "athena.db"
    _database(backup)

    verify_backup(backup, database_url="sqlite:///production.db")

    connection = sqlite3.connect(backup)
    try:
        assert connection.execute("SELECT value FROM evidence").fetchone() == ("athena",)
    finally:
        connection.close()


def test_verify_backup_rejects_corrupt_sqlite(tmp_path: Path) -> None:
    backup = tmp_path / "corrupt.db"
    backup.write_bytes(b"this is not a sqlite database")

    with pytest.raises(Exception):
        verify_backup(backup, database_url="sqlite:///production.db")


def test_verify_backup_fails_closed_for_unimplemented_backend(tmp_path: Path) -> None:
    backup = tmp_path / "athena.dump"
    backup.write_text("placeholder")

    with pytest.raises(RuntimeError, match="not implemented"):
        verify_backup(backup, database_url="postgresql://example.invalid/athena")


def test_cli_returns_nonzero_for_missing_backup(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.db")]) == 1

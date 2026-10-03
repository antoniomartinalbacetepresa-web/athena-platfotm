from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from scripts.database_backup import main


def _seed_database(
    database_path: Path,
) -> None:
    database = AthenaDatabase(
        database_path
    )
    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cli_probe (
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO cli_probe (
                value
            )
            VALUES ('cli-persisted')
            """
        )


def test_backup_verify_restore_cli_flow(
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "live.db"
    backup_path = tmp_path / "backup.db"
    restored_path = tmp_path / "restored.db"
    _seed_database(
        database_path
    )

    assert main(
        [
            "--database",
            str(database_path),
            "backup",
            "--output",
            str(backup_path),
        ]
    ) == 0
    backup_output = json.loads(
        capsys.readouterr().out
    )
    assert backup_output["status"] == "backup_created"
    assert Path(
        backup_output["manifest"]
    ).is_file()

    assert main(
        [
            "--database",
            str(database_path),
            "verify",
            "--backup",
            str(backup_path),
        ]
    ) == 0
    verify_output = json.loads(
        capsys.readouterr().out
    )
    assert verify_output["status"] == "backup_verified"

    assert main(
        [
            "--database",
            str(database_path),
            "restore",
            "--backup",
            str(backup_path),
            "--output",
            str(restored_path),
        ]
    ) == 0
    restore_output = json.loads(
        capsys.readouterr().out
    )
    assert restore_output["status"] == "backup_restored"

    connection = sqlite3.connect(
        restored_path
    )
    try:
        row = connection.execute(
            "SELECT value FROM cli_probe"
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == "cli-persisted"


def test_restore_drill_cli_flow(
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "live" / "athena.db"
    backup_path = tmp_path / "backups" / "athena.db"
    drill_directory = tmp_path / "drills"
    _seed_database(database_path)

    assert main(
        [
            "--database",
            str(database_path),
            "backup",
            "--output",
            str(backup_path),
        ]
    ) == 0
    capsys.readouterr()

    assert main(
        [
            "--database",
            str(database_path),
            "drill",
            "--backup",
            str(backup_path),
            "--working-directory",
            str(drill_directory),
        ]
    ) == 0
    drill_output = json.loads(
        capsys.readouterr().out
    )

    assert drill_output["status"] == "restore_drill_passed"
    assert drill_output["drill"]["backup"] == str(backup_path)
    assert drill_output["drill"]["schema_version"] == AthenaDatabase.SCHEMA_VERSION
    assert drill_directory.is_dir()
    assert list(drill_directory.iterdir()) == []

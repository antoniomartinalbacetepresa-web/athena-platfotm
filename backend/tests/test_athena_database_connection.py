from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase


def test_connection_is_closed_after_context_manager(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    connection = database.connect()

    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                connection_test (
                    id INTEGER PRIMARY KEY
                )
            """
        )

    with pytest.raises(
        Exception
    ):
        connection.execute(
            "SELECT 1"
        )


def test_connection_is_closed_after_exception(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    connection = database.connect()

    with pytest.raises(
        RuntimeError,
        match="fallo intencionado",
    ):
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS
                    rollback_test (
                        id INTEGER PRIMARY KEY
                    )
                """
            )

            connection.execute(
                """
                INSERT INTO rollback_test (
                    id
                )
                VALUES (1)
                """
            )

            raise RuntimeError(
                "fallo intencionado"
            )

    with pytest.raises(
        Exception
    ):
        connection.execute(
            "SELECT 1"
        )


def test_database_file_can_be_deleted_after_context_manager(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                delete_test (
                    id INTEGER PRIMARY KEY
                )
            """
        )

    assert database_path.exists()

    database_path.unlink()

    assert not database_path.exists()


def test_initialize_does_not_leave_database_locked(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    assert database_path.exists()

    database_path.unlink()

    assert not database_path.exists()


def test_connection_commit_is_preserved(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                commit_test (
                    value TEXT NOT NULL
                )
            """
        )

        connection.execute(
            """
            INSERT INTO commit_test (
                value
            )
            VALUES ('persisted')
            """
        )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT value
            FROM commit_test
            """
        ).fetchone()

    assert row is not None
    assert row["value"] == "persisted"


def test_connection_rollback_is_preserved(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena_test.db"

    database = AthenaDatabase(
        database_path
    )

    database.initialize()

    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS
                rollback_test (
                    value TEXT NOT NULL
                )
            """
        )

    with pytest.raises(
        RuntimeError,
        match="rollback",
    ):
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO rollback_test (
                    value
                )
                VALUES ('should-not-persist')
                """
            )

            raise RuntimeError(
                "rollback"
            )

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM rollback_test
            """
        ).fetchone()

    assert row is not None
    assert row["total"] == 0

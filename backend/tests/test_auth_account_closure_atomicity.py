import sqlite3
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.user_account_repository import UserAccountRepository


_PASSWORD_HASH = "argon2-placeholder-hash"
_REPLACEMENT_HASH = "argon2-replacement-placeholder-hash"


def test_close_and_anonymize_rolls_back_owner_purge_when_identity_update_fails(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    database = AthenaDatabase()
    repository = UserAccountRepository(database=database)
    account = repository.create(
        email="atomic@example.com",
        password_hash=_PASSWORD_HASH,
        display_name="Atomic User",
    )
    user_id = int(account["id"])

    # The account repository deliberately tolerates profile/portfolio tables being
    # owned by their feature repositories. Minimal owner-scoped tables make the
    # rollback invariant test independent from unrelated feature schemas.
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS athena_user_profile_preferences (
                owner_user_id INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS athena_user_portfolio_positions (
                owner_user_id INTEGER PRIMARY KEY
            );
            """
        )
        connection.execute(
            "INSERT INTO athena_user_profile_preferences (owner_user_id) VALUES (?)",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO athena_user_portfolio_positions (owner_user_id) VALUES (?)",
            (user_id,),
        )
        # Force failure after owner rows have been DELETEd but before account
        # anonymization commits. A correct transaction must restore those DELETEs.
        connection.execute(
            f"""
            CREATE TRIGGER force_account_close_failure
            BEFORE UPDATE OF email ON athena_user_accounts
            WHEN OLD.id = {user_id}
            BEGIN
                SELECT RAISE(ABORT, 'forced account close failure');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced account close failure"):
        repository.close_and_anonymize(
            user_id=user_id,
            replacement_password_hash=_REPLACEMENT_HASH,
        )

    retained = repository.get_by_id(user_id)
    assert retained is not None
    assert retained["email"] == "atomic@example.com"
    assert retained["display_name"] == "Atomic User"
    assert retained["password_hash"] == _PASSWORD_HASH
    assert int(retained["is_active"]) == 1

    with database.connect() as connection:
        profile_count = connection.execute(
            "SELECT COUNT(*) FROM athena_user_profile_preferences WHERE owner_user_id = ?",
            (user_id,),
        ).fetchone()[0]
        portfolio_count = connection.execute(
            "SELECT COUNT(*) FROM athena_user_portfolio_positions WHERE owner_user_id = ?",
            (user_id,),
        ).fetchone()[0]

    assert int(profile_count) == 1
    assert int(portfolio_count) == 1

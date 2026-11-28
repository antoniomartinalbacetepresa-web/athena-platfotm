import sqlite3
from pathlib import Path

import pytest
from pwdlib import PasswordHash

from app.database.athena_database import AthenaDatabase
from app.repositories.auth_security_repository import AuthSecurityRepository
from app.repositories.user_account_repository import UserAccountRepository


_OLD = "TestPassword-Old-1234!"
_NEW = "TestPassword-New-5678!"


def test_password_change_rolls_back_when_session_rotation_cannot_complete(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    database = AthenaDatabase()
    accounts = UserAccountRepository(database=database)
    sessions = AuthSecurityRepository(database=database)
    password_hash = PasswordHash.recommended()

    account = accounts.create(
        email="atomic-password@example.invalid",
        password_hash=password_hash.hash(_OLD),
    )
    user_id = int(account["id"])
    assert sessions.current_session_version(user_id=user_id) == 1

    new_hash = password_hash.hash(_NEW)
    accounts._SESSION_TABLE = "athena_missing_session_table_for_atomicity_test"

    with pytest.raises(sqlite3.OperationalError):
        accounts.update_password_hash_and_rotate_sessions(
            user_id=user_id,
            password_hash=new_hash,
        )

    persisted = accounts.get_by_id(user_id)
    assert persisted is not None
    persisted_hash = str(persisted["password_hash"])
    assert password_hash.verify(_OLD, persisted_hash)
    assert not password_hash.verify(_NEW, persisted_hash)
    assert sessions.current_session_version(user_id=user_id) == 1

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.auth_security_repository import AuthSecurityRepository
from app.repositories.password_recovery_repository import PasswordRecoveryRepository
from app.repositories.user_account_repository import UserAccountRepository


def _repositories(database_path: Path):
    database = AthenaDatabase(database_path)
    accounts = UserAccountRepository(database)
    security = AuthSecurityRepository(database)
    recovery = PasswordRecoveryRepository(database)
    return database, accounts, security, recovery


def test_password_reset_rolls_back_token_password_and_session_on_sql_failure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "athena.db"
    database, accounts, security, recovery = _repositories(database_path)
    account = accounts.create(
        email="atomic@example.com",
        password_hash="old-password-hash",
    )
    user_id = int(account["id"])
    assert security.current_session_version(user_id=user_id) == 1

    token = "atomic-recovery-token-with-sufficient-length-123456789"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    recovery.create(
        token_hash=token_hash,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TRIGGER fail_recovery_session_rotation
            BEFORE UPDATE ON athena_auth_user_sessions
            WHEN NEW.session_version > OLD.session_version
            BEGIN
                SELECT RAISE(ABORT, 'forced session rotation failure');
            END;
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="forced session rotation failure"):
        recovery.complete_password_reset(
            token_hash=token_hash,
            user_id=user_id,
            password_hash="new-password-hash",
        )

    with database.connect() as connection:
        persisted_account = connection.execute(
            "SELECT password_hash FROM athena_user_accounts WHERE id = ?",
            (user_id,),
        ).fetchone()
        persisted_token = connection.execute(
            "SELECT consumed_at FROM athena_password_recovery_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        persisted_session = connection.execute(
            "SELECT session_version FROM athena_auth_user_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        connection.execute("DROP TRIGGER fail_recovery_session_rotation")

    assert persisted_account is not None
    assert persisted_account["password_hash"] == "old-password-hash"
    assert persisted_token is not None
    assert persisted_token["consumed_at"] is None
    assert persisted_session is not None
    assert int(persisted_session["session_version"]) == 1

    assert recovery.complete_password_reset(
        token_hash=token_hash,
        user_id=user_id,
        password_hash="new-password-hash",
    )

    with database.connect() as connection:
        committed_account = connection.execute(
            "SELECT password_hash FROM athena_user_accounts WHERE id = ?",
            (user_id,),
        ).fetchone()
        committed_token = connection.execute(
            "SELECT consumed_at FROM athena_password_recovery_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        committed_session = connection.execute(
            "SELECT session_version FROM athena_auth_user_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    assert committed_account is not None
    assert committed_account["password_hash"] == "new-password-hash"
    assert committed_token is not None
    assert committed_token["consumed_at"] is not None
    assert committed_session is not None
    assert int(committed_session["session_version"]) == 2

    assert not recovery.complete_password_reset(
        token_hash=token_hash,
        user_id=user_id,
        password_hash="another-password-hash",
    )

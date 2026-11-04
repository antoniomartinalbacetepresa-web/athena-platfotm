from pathlib import Path

from pwdlib import PasswordHash

from app.database.athena_database import AthenaDatabase
from app.repositories.user_account_repository import UserAccountRepository
from app.services.auth_service import AuthService


_PASSWORD = "CorrectHorseBatteryStaple!"
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"


class _FailingSessionCleanup:
    def revoke_all_sessions(self, *, user_id: int) -> int:
        del user_id
        raise RuntimeError("injected session cleanup failure")


def test_closed_account_remains_successful_when_session_cleanup_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    database = AthenaDatabase()
    accounts = UserAccountRepository(database=database)
    password_hash = PasswordHash.recommended()
    account = accounts.create(
        email="closure-session@example.invalid",
        password_hash=password_hash.hash(_PASSWORD),
        display_name="Closure Session Test",
    )

    service = AuthService(
        repository=accounts,
        security_repository=_FailingSessionCleanup(),
        secret_key=_SECRET,
    )
    assert service.close_account(
        user_id=int(account["id"]),
        current_password=_PASSWORD,
    ) is True

    persisted = accounts.get_by_id(int(account["id"]))
    assert persisted is not None
    assert int(persisted["is_active"]) == 0
    assert persisted["display_name"] is None
    assert persisted["email"] == f"closed-{int(account['id'])}@account.invalid"

from pathlib import Path

from fastapi.testclient import TestClient

import app.api.auth as auth_api
from app.main import app
from app.repositories.user_account_repository import UserAccountRepository


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"
_EMAIL = "closure-cleanup@example.invalid"


class _FailingRecoveryCleanup:
    def invalidate(self, *, user_id: int) -> None:
        del user_id
        raise RuntimeError("injected recovery cleanup failure")


def test_completed_account_closure_is_not_reported_as_failed_when_recovery_cleanup_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)

    created = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _PASSWORD},
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/token",
        data={"username": _EMAIL, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])

    monkeypatch.setattr(
        auth_api,
        "_recovery_service",
        lambda: _FailingRecoveryCleanup(),
    )
    closed = client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": _PASSWORD},
    )

    assert closed.status_code == 204, closed.text
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 401
    assert UserAccountRepository().get_by_email(_EMAIL) is None

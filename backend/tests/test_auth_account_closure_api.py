from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.user_account_repository import UserAccountRepository


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def _register_and_login(monkeypatch, tmp_path: Path) -> str:
    _configure(monkeypatch, tmp_path)
    created = client.post(
        "/api/v1/auth/register",
        json={"email": "close@example.com", "password": _PASSWORD},
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/token",
        data={"username": "close@example.com", "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def test_close_account_requires_current_password_and_preserves_account_on_failure(monkeypatch, tmp_path: Path) -> None:
    token = _register_and_login(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "WrongPassword123!"},
    )
    assert response.status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200


def test_close_account_deactivates_identity_revokes_sessions_and_blocks_relogin(monkeypatch, tmp_path: Path) -> None:
    first_token = _register_and_login(monkeypatch, tmp_path)
    second_login = client.post(
        "/api/v1/auth/token",
        data={"username": "close@example.com", "password": _PASSWORD},
    )
    assert second_login.status_code == 200
    second_token = str(second_login.json()["access_token"])

    closed = client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {first_token}"},
        json={"currentPassword": _PASSWORD},
    )
    assert closed.status_code == 204, closed.text

    for token in (first_token, second_token):
        assert client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 401

    relogin = client.post(
        "/api/v1/auth/token",
        data={"username": "close@example.com", "password": _PASSWORD},
    )
    assert relogin.status_code == 401

    account = UserAccountRepository().get_by_email("close@example.com")
    assert account is not None
    assert int(account["is_active"]) == 0


def test_closed_account_cannot_be_recovered(monkeypatch, tmp_path: Path) -> None:
    token = _register_and_login(monkeypatch, tmp_path)
    assert client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": _PASSWORD},
    ).status_code == 204

    # The public endpoint stays enumeration-safe. The service contract guarantees
    # inactive accounts do not receive a usable challenge.
    from app.services.password_recovery_service import PasswordRecoveryService

    assert PasswordRecoveryService().request(email="close@example.com") is None

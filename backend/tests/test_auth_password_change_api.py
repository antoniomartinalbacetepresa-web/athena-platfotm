from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "test-secret-only-0123456789abcdef0123456789abcdef"
_OLD = "TestPassword-Old-1234!"
_NEW = "TestPassword-New-5678!"


def _setup(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)
    created = client.post(
        "/api/v1/auth/register",
        json={"email": "password-test@example.invalid", "password": _OLD},
    )
    assert created.status_code == 201, created.text


def _login(password: str):
    return client.post(
        "/api/v1/auth/token",
        data={"username": "password-test@example.invalid", "password": password},
    )


def test_password_change_requires_authentication(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/auth/change-password",
        json={"currentPassword": _OLD, "newPassword": _NEW},
    )
    assert response.status_code == 401


def test_password_change_rejects_wrong_current_secret(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)
    token = _login(_OLD).json()["access_token"]
    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": "Definitely-Wrong-1234!", "newPassword": _NEW},
    )
    assert response.status_code == 401
    assert _login(_OLD).status_code == 200


def test_password_change_revokes_old_sessions_and_requires_new_secret(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)
    first = _login(_OLD).json()["access_token"]
    second = _login(_OLD).json()["access_token"]

    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {first}"},
        json={"currentPassword": _OLD, "newPassword": _NEW},
    )
    assert changed.status_code == 204, changed.text

    for token in (first, second):
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 401

    assert _login(_OLD).status_code == 401
    fresh = _login(_NEW)
    assert fresh.status_code == 200


def test_password_change_rejects_extra_identity_field(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch, tmp_path)
    token = _login(_OLD).json()["access_token"]
    response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": _OLD, "newPassword": _NEW, "userId": 999},
    )
    assert response.status_code == 422

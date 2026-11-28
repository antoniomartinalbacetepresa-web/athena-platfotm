from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_EMAIL = "lifecycle@example.com"
_INITIAL_PASSWORD = "CorrectHorseBatteryStaple!"
_ROTATED_PASSWORD = "RotatedHorseBatteryStaple!"


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)


def _login(password: str):
    return client.post(
        "/api/v1/auth/token",
        data={"username": _EMAIL, "password": password},
    )


def _me(token: str):
    return client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )


def _logout(token: str):
    return client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )


def _logout_all(token: str):
    return client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_full_account_lifecycle_revokes_stale_credentials_and_releases_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Exercise the security-critical account lifecycle through the public API.

    This intentionally crosses registration, individual/global logout, concurrent
    sessions, password rotation, stale-session rejection, account closure and clean
    re-registration so regressions cannot leave old bearer credentials or a closed
    identity usable.
    """
    _configure(monkeypatch, tmp_path)

    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": _EMAIL,
            "password": _INITIAL_PASSWORD,
            "displayName": "Lifecycle User",
        },
    )
    assert created.status_code == 201, created.text
    original_account_id = int(created.json()["account"]["id"])

    first_login = _login(_INITIAL_PASSWORD)
    second_login = _login(_INITIAL_PASSWORD)
    assert first_login.status_code == 200, first_login.text
    assert second_login.status_code == 200, second_login.text
    first_token = first_login.json()["access_token"]
    second_token = second_login.json()["access_token"]
    assert first_token != second_token
    assert _me(first_token).status_code == 200
    assert _me(second_token).status_code == 200

    # Individual logout is scoped to exactly the presented bearer. A concurrent
    # session must remain valid, proving that normal logout does not silently act
    # like a global account revocation.
    logged_out = _logout(first_token)
    assert logged_out.status_code == 204, logged_out.text
    assert _me(first_token).status_code == 401
    assert _me(second_token).status_code == 200

    replacement_login = _login(_INITIAL_PASSWORD)
    assert replacement_login.status_code == 200, replacement_login.text
    replacement_token = replacement_login.json()["access_token"]
    assert _me(replacement_token).status_code == 200

    # Global logout is the inverse boundary: every bearer issued under the current
    # session version must become unusable immediately, including the caller.
    logged_out_all = _logout_all(second_token)
    assert logged_out_all.status_code == 204, logged_out_all.text
    assert _me(second_token).status_code == 401
    assert _me(replacement_token).status_code == 401
    assert _me(first_token).status_code == 401

    # Authentication remains possible after an explicit logout-all; obtain two new
    # sessions so password rotation can prove its stronger all-session boundary too.
    first_login = _login(_INITIAL_PASSWORD)
    second_login = _login(_INITIAL_PASSWORD)
    assert first_login.status_code == 200, first_login.text
    assert second_login.status_code == 200, second_login.text
    first_token = first_login.json()["access_token"]
    second_token = second_login.json()["access_token"]
    assert first_token != second_token

    changed = client.post(
        "/api/v1/auth/change-password",
        json={
            "currentPassword": _INITIAL_PASSWORD,
            "newPassword": _ROTATED_PASSWORD,
        },
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert changed.status_code == 204, changed.text

    # Password rotation is an all-session security boundary: neither bearer that
    # existed before the change may survive it.
    assert _me(first_token).status_code == 401
    assert _me(second_token).status_code == 401
    assert _login(_INITIAL_PASSWORD).status_code == 401

    fresh_login = _login(_ROTATED_PASSWORD)
    assert fresh_login.status_code == 200, fresh_login.text
    fresh_token = fresh_login.json()["access_token"]
    fresh_me = _me(fresh_token)
    assert fresh_me.status_code == 200, fresh_me.text
    assert int(fresh_me.json()["account"]["id"]) == original_account_id

    closed = client.post(
        "/api/v1/auth/close-account",
        json={"currentPassword": _ROTATED_PASSWORD},
        headers={"Authorization": f"Bearer {fresh_token}"},
    )
    assert closed.status_code == 204, closed.text

    # Closure must immediately kill the last live credential and prevent password
    # authentication with both the current and historical passwords.
    assert _me(fresh_token).status_code == 401
    assert _login(_ROTATED_PASSWORD).status_code == 401
    assert _login(_INITIAL_PASSWORD).status_code == 401

    # The anonymized account releases its email so a returning person receives a
    # distinct identity rather than silently reactivating the closed account.
    returned = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _INITIAL_PASSWORD},
    )
    assert returned.status_code == 201, returned.text
    returned_account_id = int(returned.json()["account"]["id"])
    assert returned_account_id != original_account_id

    returned_login = _login(_INITIAL_PASSWORD)
    assert returned_login.status_code == 200, returned_login.text
    returned_token = returned_login.json()["access_token"]
    returned_me = _me(returned_token)
    assert returned_me.status_code == 200, returned_me.text
    assert int(returned_me.json()["account"]["id"]) == returned_account_id

    # Old credentials from the closed identity stay dead even after the same email
    # has legitimately been registered again by a new account row.
    assert _me(first_token).status_code == 401
    assert _me(second_token).status_code == 401
    assert _me(fresh_token).status_code == 401
    assert _me(replacement_token).status_code == 401

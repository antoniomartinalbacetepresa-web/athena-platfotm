from __future__ import annotations

import base64
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


AUTH_SECRET = "athena-lifecycle-test-secret-0123456789abcdef0123456789abcdef"
PROFILE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
ORIGINAL_PASSWORD = "CorrectHorseBatteryStaple!"
NEW_PASSWORD = "NewCorrectHorseBatteryStaple!"
EMAIL = "lifecycle@example.com"


def _configure(monkeypatch, tmp_path) -> str:
    database_path = str(tmp_path / "athena_account_lifecycle.db")
    monkeypatch.setenv("ATHENA_DATABASE_PATH", database_path)
    monkeypatch.setenv("ATHENA_AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", PROFILE_KEY)
    monkeypatch.setenv(
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH",
        str(tmp_path / "portfolio_event_ledger.jsonl"),
    )
    return database_path


def _login(client: TestClient, password: str):
    return client.post(
        "/api/v1/auth/token",
        data={"username": EMAIL, "password": password},
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_account_lifecycle_across_profile_and_portfolio(
    monkeypatch,
    tmp_path,
) -> None:
    """Regression acceptance for the owner-scoped account lifecycle.

    This is engineering evidence only: it deliberately uses an isolated local
    database and must not be interpreted as deployed SMTP, secret-manager,
    backup/restore, or other production-readiness evidence.
    """
    database_path = _configure(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/register",
            json={
                "email": EMAIL,
                "password": ORIGINAL_PASSWORD,
                "displayName": "Lifecycle User",
            },
        )
        assert created.status_code == 201, created.text
        original_user_id = int(created.json()["account"]["id"])

        first_login = _login(client, ORIGINAL_PASSWORD)
        assert first_login.status_code == 200, first_login.text
        original_token = str(first_login.json()["access_token"])

        profile = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(original_token),
            json={
                "riskTolerance": "balanced",
                "investmentHorizonYears": 12,
                "baseCurrency": "EUR",
                "objective": "long_term_growth",
            },
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["policy"]["sensitivePreferencesEncrypted"] is True

        position = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(original_token),
            json={
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "quantity": 3.5,
            },
        )
        assert position.status_code == 200, position.text
        assert position.json()["data"]["quantity"] == 3.5

        changed = client.post(
            "/api/v1/auth/change-password",
            headers=_headers(original_token),
            json={
                "currentPassword": ORIGINAL_PASSWORD,
                "newPassword": NEW_PASSWORD,
            },
        )
        assert changed.status_code == 204, changed.text

        # Password rotation must revoke the bearer used to perform it.
        assert client.get(
            "/api/v1/auth/me",
            headers=_headers(original_token),
        ).status_code == 401
        assert _login(client, ORIGINAL_PASSWORD).status_code == 401

        second_login = _login(client, NEW_PASSWORD)
        assert second_login.status_code == 200, second_login.text
        rotated_token = str(second_login.json()["access_token"])

        persisted_profile = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(rotated_token),
        )
        assert persisted_profile.status_code == 200, persisted_profile.text
        assert persisted_profile.json()["data"]["preferences"] == {
            "riskTolerance": "balanced",
            "investmentHorizonYears": 12,
            "baseCurrency": "EUR",
            "objective": "long_term_growth",
        }

        persisted_portfolio = client.get(
            "/api/v1/user/portfolio",
            headers=_headers(rotated_token),
        )
        assert persisted_portfolio.status_code == 200, persisted_portfolio.text
        assert persisted_portfolio.json()["data"]["positionCount"] == 1
        assert persisted_portfolio.json()["data"]["positions"][0]["symbol"] == "AAPL"

        closed = client.post(
            "/api/v1/auth/close-account",
            headers=_headers(rotated_token),
            json={"currentPassword": NEW_PASSWORD},
        )
        assert closed.status_code == 204, closed.text

        for path in (
            "/api/v1/auth/me",
            "/api/v1/user/profile/preferences",
            "/api/v1/user/portfolio",
        ):
            assert client.get(path, headers=_headers(rotated_token)).status_code == 401

        assert _login(client, NEW_PASSWORD).status_code == 401

        # The same email may return as a new account, but no mutable personal
        # state from the closed identity may cross the lifecycle boundary.
        returned = client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "password": ORIGINAL_PASSWORD},
        )
        assert returned.status_code == 201, returned.text
        returned_user_id = int(returned.json()["account"]["id"])
        assert returned_user_id != original_user_id

        returned_login = _login(client, ORIGINAL_PASSWORD)
        assert returned_login.status_code == 200, returned_login.text
        returned_token = str(returned_login.json()["access_token"])

        clean_profile = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(returned_token),
        )
        assert clean_profile.status_code == 200
        assert clean_profile.json()["status"] == "not_configured"
        assert clean_profile.json()["data"] is None

        clean_portfolio = client.get(
            "/api/v1/user/portfolio",
            headers=_headers(returned_token),
        )
        assert clean_portfolio.status_code == 200
        assert clean_portfolio.json()["data"]["positionCount"] == 0
        assert clean_portfolio.json()["data"]["positions"] == []

    with sqlite3.connect(database_path) as connection:
        profile_rows = connection.execute(
            "SELECT COUNT(*) FROM athena_user_profile_preferences WHERE owner_user_id = ?",
            (original_user_id,),
        ).fetchone()
        portfolio_rows = connection.execute(
            "SELECT COUNT(*) FROM athena_user_portfolio_positions WHERE owner_user_id = ?",
            (original_user_id,),
        ).fetchone()
        original_account = connection.execute(
            "SELECT email, display_name, is_active FROM athena_user_accounts WHERE id = ?",
            (original_user_id,),
        ).fetchone()

    assert profile_rows is not None and int(profile_rows[0]) == 0
    assert portfolio_rows is not None and int(portfolio_rows[0]) == 0
    assert original_account == (
        f"closed-{original_user_id}@account.invalid",
        None,
        0,
    )

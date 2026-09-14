import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.encrypted_user_profile_repository import EncryptedUserProfileRepository
from app.repositories.user_account_repository import UserAccountRepository
from app.repositories.user_portfolio_repository import UserPortfolioRepository


client = TestClient(app)
_SECRET = "athena-test-secret-0123456789abcdef0123456789abcdef"
_PASSWORD = "CorrectHorseBatteryStaple!"
_PROFILE_KEY = base64.urlsafe_b64encode(b"p" * 32).decode("ascii")


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", _SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", _PROFILE_KEY)


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


def _account_id(token: str) -> int:
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["account"]["id"])


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


def test_close_account_anonymizes_identity_revokes_sessions_and_blocks_relogin(monkeypatch, tmp_path: Path) -> None:
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

    # Closure must release the original direct identifier rather than retaining
    # a queryable inactive identity under the person's email address.
    assert UserAccountRepository().get_by_email("close@example.com") is None


def test_close_account_purges_mutable_profile_and_current_portfolio_state(monkeypatch, tmp_path: Path) -> None:
    token = _register_and_login(monkeypatch, tmp_path)
    owner_id = _account_id(token)
    profile = EncryptedUserProfileRepository()
    portfolio = UserPortfolioRepository()
    profile.upsert(
        owner_user_id=owner_id,
        preferences={
            "riskTolerance": "balanced",
            "investmentHorizonYears": 10,
            "baseCurrency": "EUR",
            "objective": "long_term_growth",
            "availableCapital": 25000.0,
        },
    )
    portfolio.upsert(
        owner_user_id=owner_id,
        symbol="AAPL",
        exchange="NASDAQ",
        quantity=3.0,
        average_purchase_price=190.5,
    )
    assert profile.get_for_owner(owner_id) is not None
    assert len(portfolio.list_for_owner(owner_id)) == 1

    closed = client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": _PASSWORD},
    )
    assert closed.status_code == 204, closed.text

    # Verify physical row removal directly, not merely loss of authenticated API access.
    assert profile.get_for_owner(owner_id) is None
    assert portfolio.list_for_owner(owner_id) == []
    closed_identity = UserAccountRepository().get_by_id(owner_id)
    assert closed_identity is not None
    assert int(closed_identity["is_active"]) == 0
    assert closed_identity["display_name"] is None
    assert closed_identity["email"] == f"closed-{owner_id}@account.invalid"


def test_closed_account_cannot_be_recovered(monkeypatch, tmp_path: Path) -> None:
    token = _register_and_login(monkeypatch, tmp_path)
    assert client.post(
        "/api/v1/auth/close-account",
        headers={"Authorization": f"Bearer {token}"},
        json={"currentPassword": _PASSWORD},
    ).status_code == 204

    # The public endpoint stays enumeration-safe. The service contract guarantees
    # closed/anonymized accounts do not receive a usable challenge.
    from app.services.password_recovery_service import PasswordRecoveryService

    assert PasswordRecoveryService().request(email="close@example.com") is None

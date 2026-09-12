from __future__ import annotations

import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"
TEST_PROFILE_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")
PASSWORD = "correct horse battery staple"


def _configure(monkeypatch, tmp_path) -> str:
    database_path = str(tmp_path / "athena_user_portfolio_cost_basis.db")
    monkeypatch.setenv("ATHENA_DATABASE_PATH", database_path)
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", TEST_PROFILE_KEY)
    return database_path


def _register_and_token(client: TestClient, *, email: str) -> str:
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "displayName": email.split("@", 1)[0]},
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_average_purchase_price_is_owner_scoped_and_encrypted(monkeypatch, tmp_path) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="cost-basis-a@example.com")
        token_b = _register_and_token(client, email="cost-basis-b@example.com")

        stored = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token_a),
            json={
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "quantity": 12.5,
                "averagePurchasePrice": 187.25,
            },
        )
        assert stored.status_code == 200, stored.text
        body = stored.json()
        assert body["data"]["averagePurchasePrice"] == pytest.approx(187.25)
        assert body["policy"]["ownerDerivedFromAuthenticatedToken"] is True
        assert body["policy"]["sensitiveCostBasisStored"] is True
        assert body["policy"]["sensitiveCostBasisEncrypted"] is True
        assert body["policy"]["storageEncrypted"] is False
        assert body["policy"]["productionEligible"] is False
        assert body["policy"]["automaticTrading"] is False

        loaded_a = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert loaded_a.status_code == 200, loaded_a.text
        assert loaded_a.json()["data"]["positions"][0]["averagePurchasePrice"] == pytest.approx(187.25)

        loaded_b = client.get("/api/v1/user/portfolio", headers=_headers(token_b))
        assert loaded_b.status_code == 200, loaded_b.text
        assert loaded_b.json()["data"]["positions"] == []

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT average_purchase_price_key_version,
                   average_purchase_price_nonce_b64,
                   average_purchase_price_ciphertext_b64
            FROM athena_user_portfolio_positions
            WHERE symbol = 'AAPL'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1]
    assert row[2]
    serialized = " ".join(str(value) for value in row)
    assert "187.25" not in serialized
    assert "averagePurchasePrice" not in serialized


def test_quantity_only_upsert_preserves_existing_encrypted_cost_basis(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="preserve-cost-basis@example.com")
        first = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token),
            json={
                "symbol": "MSFT",
                "exchange": "NASDAQ",
                "quantity": 2,
                "averagePurchasePrice": 405.5,
            },
        )
        assert first.status_code == 200, first.text

        updated = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token),
            json={"symbol": "MSFT", "exchange": "NASDAQ", "quantity": 3},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["quantity"] == 3.0
        assert updated.json()["data"]["averagePurchasePrice"] == pytest.approx(405.5)


def test_average_purchase_price_rejects_invalid_numeric_boundaries(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="invalid-cost-basis@example.com")
        for value in (0, -1, 1_000_000_000_000.01, float("nan"), float("inf"), float("-inf")):
            response = client.put(
                "/api/v1/user/portfolio/positions",
                headers=_headers(token),
                json={
                    "symbol": "NVDA",
                    "exchange": "NASDAQ",
                    "quantity": 1,
                    "averagePurchasePrice": value,
                },
            )
            assert response.status_code == 400, (value, response.text)
            assert "averagePurchasePrice" in response.json()["detail"]


def test_legacy_position_without_cost_basis_does_not_require_encryption_key(monkeypatch, tmp_path) -> None:
    database_path = str(tmp_path / "athena_legacy_portfolio.db")
    monkeypatch.setenv("ATHENA_DATABASE_PATH", database_path)
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)
    monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_KEY", raising=False)

    with TestClient(app) as client:
        token = _register_and_token(client, email="legacy-position@example.com")
        stored = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token),
            json={"symbol": "GOOG", "exchange": "NASDAQ", "quantity": 4},
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["data"]["averagePurchasePrice"] is None

        loaded = client.get("/api/v1/user/portfolio", headers=_headers(token))
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["data"]["positions"][0]["averagePurchasePrice"] is None

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"


def _configure(tmp_path) -> None:
    os.environ["ATHENA_DATABASE_PATH"] = str(tmp_path / "athena_user_portfolio.db")
    os.environ["ATHENA_AUTH_SECRET"] = TEST_SECRET


def _register_and_token(client: TestClient, *, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "displayName": email.split("@", 1)[0],
        },
    )
    assert response.status_code == 201, response.text

    response = client.post(
        "/api/v1/auth/token",
        data={
            "username": email,
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_personal_portfolio_requires_authentication(tmp_path) -> None:
    _configure(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/user/portfolio")
    assert response.status_code == 401


def test_users_can_only_see_and_delete_their_own_positions(tmp_path) -> None:
    _configure(tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="owner-a@example.com")
        token_b = _register_and_token(client, email="owner-b@example.com")

        created = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token_a),
            json={"symbol": " aapl ", "exchange": " nasdaq ", "quantity": 12.5},
        )
        assert created.status_code == 200, created.text
        position = created.json()["data"]
        position_id = int(position["id"])
        assert position["symbol"] == "AAPL"
        assert position["exchange"] == "NASDAQ"
        assert position["quantity"] == 12.5
        assert "ownerUserId" not in position

        own = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert own.status_code == 200
        assert own.json()["data"]["positionCount"] == 1
        assert own.json()["data"]["positions"][0]["id"] == position_id
        assert own.json()["policy"]["ownerDerivedFromAuthenticatedToken"] is True
        assert own.json()["policy"]["productionEligible"] is False
        assert own.json()["policy"]["storageEncrypted"] is False

        foreign = client.get("/api/v1/user/portfolio", headers=_headers(token_b))
        assert foreign.status_code == 200
        assert foreign.json()["data"]["positions"] == []

        foreign_delete = client.delete(
            f"/api/v1/user/portfolio/positions/{position_id}",
            headers=_headers(token_b),
        )
        assert foreign_delete.status_code == 404

        still_owned = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert still_owned.json()["data"]["positionCount"] == 1

        own_delete = client.delete(
            f"/api/v1/user/portfolio/positions/{position_id}",
            headers=_headers(token_a),
        )
        assert own_delete.status_code == 204

        empty = client.get("/api/v1/user/portfolio", headers=_headers(token_a))
        assert empty.json()["data"]["positions"] == []


def test_client_cannot_supply_portfolio_owner(tmp_path) -> None:
    _configure(tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="owner@example.com")
        response = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token),
            json={
                "symbol": "MSFT",
                "exchange": "NASDAQ",
                "quantity": 3,
                "ownerUserId": 999999,
            },
        )
    assert response.status_code == 422


def test_upsert_updates_only_the_authenticated_owners_matching_position(tmp_path) -> None:
    _configure(tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="upsert-a@example.com")
        token_b = _register_and_token(client, email="upsert-b@example.com")

        for token, quantity in ((token_a, 1), (token_b, 9)):
            response = client.put(
                "/api/v1/user/portfolio/positions",
                headers=_headers(token),
                json={"symbol": "MSFT", "exchange": "NASDAQ", "quantity": quantity},
            )
            assert response.status_code == 200

        response = client.put(
            "/api/v1/user/portfolio/positions",
            headers=_headers(token_a),
            json={"symbol": "MSFT", "exchange": "NASDAQ", "quantity": 4},
        )
        assert response.status_code == 200

        portfolio_a = client.get("/api/v1/user/portfolio", headers=_headers(token_a)).json()
        portfolio_b = client.get("/api/v1/user/portfolio", headers=_headers(token_b)).json()
        assert portfolio_a["data"]["positions"][0]["quantity"] == 4.0
        assert portfolio_b["data"]["positions"][0]["quantity"] == 9.0

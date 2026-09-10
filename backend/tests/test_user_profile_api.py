from __future__ import annotations

import base64
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"
TEST_PROFILE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
PASSWORD = "correct horse battery staple"


def _configure(monkeypatch, tmp_path) -> str:
    database_path = str(tmp_path / "athena_user_profile.db")
    monkeypatch.setenv("ATHENA_DATABASE_PATH", database_path)
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", TEST_PROFILE_KEY)
    return database_path


def _register_and_token(client: TestClient, *, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "displayName": email.split("@", 1)[0],
        },
    )
    assert response.status_code == 201, response.text
    response = client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _preferences() -> dict[str, object]:
    return {
        "riskTolerance": "balanced",
        "investmentHorizonYears": 12,
        "baseCurrency": "eur",
        "objective": "long_term_growth",
    }


def test_preferences_require_authentication(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/user/profile/preferences")
    assert response.status_code == 401


def test_profile_storage_fails_closed_without_encryption_key(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("ATHENA_PROFILE_ENCRYPTION_KEY")
    with TestClient(app) as client:
        token = _register_and_token(client, email="missing-key@example.com")
        response = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
        )
    assert response.status_code == 503


def test_preferences_are_owner_scoped_and_ciphertext_only(monkeypatch, tmp_path) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="profile-a@example.com")
        token_b = _register_and_token(client, email="profile-b@example.com")

        stored = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
            json=_preferences(),
        )
        assert stored.status_code == 200, stored.text
        body = stored.json()
        assert body["data"]["preferences"]["baseCurrency"] == "EUR"
        assert body["policy"]["sensitivePreferencesEncrypted"] is True
        assert body["policy"]["encryption"] == "AES-256-GCM"
        assert body["policy"]["productionEligible"] is False

        own = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
        )
        foreign = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_b),
        )
        assert own.status_code == 200
        assert own.json()["status"] == "configured"
        assert foreign.status_code == 200
        assert foreign.json()["status"] == "not_configured"
        assert foreign.json()["data"] is None

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT nonce_b64, ciphertext_b64 FROM athena_user_profile_preferences"
        ).fetchone()
    assert row is not None
    serialized = " ".join(str(value) for value in row)
    assert "balanced" not in serialized
    assert "long_term_growth" not in serialized
    assert "EUR" not in serialized


def test_client_cannot_supply_owner_or_unknown_fields(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="profile-owner@example.com")
        payload = _preferences()
        payload["ownerUserId"] = 999
        response = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=payload,
        )
    assert response.status_code == 422


def test_delete_only_removes_authenticated_owners_preferences(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="delete-a@example.com")
        token_b = _register_and_token(client, email="delete-b@example.com")
        for token, risk in ((token_a, "balanced"), (token_b, "aggressive")):
            payload = _preferences()
            payload["riskTolerance"] = risk
            response = client.put(
                "/api/v1/user/profile/preferences",
                headers=_headers(token),
                json=payload,
            )
            assert response.status_code == 200

        deleted = client.delete(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
        )
        assert deleted.status_code == 204
        assert client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
        ).json()["status"] == "not_configured"
        assert client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_b),
        ).json()["data"]["preferences"]["riskTolerance"] == "aggressive"


def test_tampered_ciphertext_is_rejected(monkeypatch, tmp_path) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="tamper@example.com")
        response = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=_preferences(),
        )
        assert response.status_code == 200

        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT ciphertext_b64 FROM athena_user_profile_preferences"
            ).fetchone()
            assert row is not None
            ciphertext = str(row[0])
            replacement = "A" if ciphertext[0] != "A" else "B"
            connection.execute(
                "UPDATE athena_user_profile_preferences SET ciphertext_b64 = ?",
                (replacement + ciphertext[1:],),
            )
            connection.commit()

        response = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
        )
    assert response.status_code == 500
    assert "integridad" in response.json()["detail"].lower()

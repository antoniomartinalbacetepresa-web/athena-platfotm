from __future__ import annotations

import base64
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"
TEST_PROFILE_KEY = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")
PASSWORD = "correct horse battery staple"


def _configure(monkeypatch, tmp_path) -> str:
    database_path = str(tmp_path / "athena_profile_available_capital.db")
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


def _payload(*, available_capital: object = 125_000.75) -> dict[str, object]:
    return {
        "riskTolerance": "balanced",
        "investmentHorizonYears": 12,
        "baseCurrency": "eur",
        "objective": "balanced_growth",
        "experienceLevel": "intermediate",
        "liquidityNeed": "medium",
        "maxDrawdownTolerancePct": 25,
        "availableCapital": available_capital,
    }


def test_available_capital_is_owner_scoped_and_encrypted(monkeypatch, tmp_path) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="capital-a@example.com")
        token_b = _register_and_token(client, email="capital-b@example.com")

        stored = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
            json=_payload(),
        )
        assert stored.status_code == 200, stored.text
        body = stored.json()
        assert body["data"]["preferences"]["availableCapital"] == 125_000.75
        assert body["data"]["preferences"]["baseCurrency"] == "EUR"
        assert "availableCapital" in body["policy"]["encryptedPreferenceFields"]
        assert body["policy"]["automaticRecommendationOverrides"] is False
        assert body["policy"]["automaticTrading"] is False

        loaded_a = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
        )
        assert loaded_a.status_code == 200
        assert loaded_a.json()["data"]["preferences"]["availableCapital"] == 125_000.75

        loaded_b = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_b),
        )
        assert loaded_b.status_code == 200
        assert loaded_b.json()["status"] == "not_configured"
        assert loaded_b.json()["data"] is None

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT nonce_b64, ciphertext_b64 FROM athena_user_profile_preferences"
        ).fetchone()
    assert row is not None
    serialized = " ".join(str(value) for value in row)
    assert "availableCapital" not in serialized
    assert "balanced_growth" not in serialized
    assert "EUR" not in serialized


def test_available_capital_is_optional_for_backward_compatibility(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="capital-legacy@example.com")
        payload = _payload()
        payload.pop("availableCapital")
        response = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=payload,
        )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["preferences"]["availableCapital"] is None


def test_available_capital_rejects_invalid_numeric_values(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="capital-invalid@example.com")
        for invalid in (-0.01, 1_000_000_000_000.01, "not-a-number"):
            response = client.put(
                "/api/v1/user/profile/preferences",
                headers=_headers(token),
                json=_payload(available_capital=invalid),
            )
            assert response.status_code == 422, (invalid, response.text)

        for raw in ("NaN", "Infinity", "-Infinity"):
            response = client.put(
                "/api/v1/user/profile/preferences",
                headers={**_headers(token), "Content-Type": "application/json"},
                content=(
                    '{"riskTolerance":"balanced","investmentHorizonYears":12,'
                    '"baseCurrency":"EUR","objective":"balanced_growth",'
                    f'"availableCapital":{raw}'
                    "}"
                ),
            )
            assert response.status_code == 422, (raw, response.text)

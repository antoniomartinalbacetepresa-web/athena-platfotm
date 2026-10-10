from __future__ import annotations

import base64
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"
TEST_PROFILE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
PASSWORD = "correct horse battery staple"


def _configure(monkeypatch, tmp_path) -> str:
    database_path = str(tmp_path / "athena_profile_richer.db")
    monkeypatch.setenv("ATHENA_DATABASE_PATH", database_path)
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", TEST_PROFILE_KEY)
    return database_path


def _token(client: TestClient) -> str:
    email = "richer-profile@example.com"
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "displayName": "Richer"},
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


def _payload() -> dict[str, object]:
    return {
        "riskTolerance": "growth",
        "investmentHorizonYears": 15,
        "baseCurrency": "eur",
        "objective": "long_term_growth",
        "experienceLevel": "intermediate",
        "liquidityNeed": "low",
        "maxDrawdownTolerancePct": 30,
    }


def test_richer_personalization_round_trips_only_inside_encrypted_profile(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _token(client)
        response = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=_payload(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        preferences = body["data"]["preferences"]
        assert preferences["experienceLevel"] == "intermediate"
        assert preferences["liquidityNeed"] == "low"
        assert preferences["maxDrawdownTolerancePct"] == 30
        assert body["policy"]["automaticRecommendationOverrides"] is False
        assert "maxDrawdownTolerancePct" in body["policy"]["encryptedPreferenceFields"]

        loaded = client.get(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
        )
        assert loaded.status_code == 200
        assert loaded.json()["data"]["preferences"] == preferences

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT nonce_b64, ciphertext_b64 FROM athena_user_profile_preferences"
        ).fetchone()
    assert row is not None
    serialized = " ".join(str(value) for value in row)
    assert "intermediate" not in serialized
    assert "low" not in serialized
    # Do not search for a short numeric value such as "30" in randomized
    # Base64 ciphertext: those characters may legitimately occur by chance.
    # The sensitive field name is a robust plaintext-leak sentinel.
    assert "maxDrawdownTolerancePct" not in serialized


def test_legacy_four_field_payload_remains_accepted(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _token(client)
        payload = _payload()
        payload.pop("experienceLevel")
        payload.pop("liquidityNeed")
        payload.pop("maxDrawdownTolerancePct")
        response = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=payload,
        )
    assert response.status_code == 200, response.text
    stored = response.json()["data"]["preferences"]
    assert stored["experienceLevel"] is None
    assert stored["liquidityNeed"] is None
    assert stored["maxDrawdownTolerancePct"] is None


def test_richer_personalization_rejects_invalid_categories_and_drawdown(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _token(client)
        for field, invalid in (
            ("experienceLevel", "expert"),
            ("liquidityNeed", "urgent"),
            ("maxDrawdownTolerancePct", 61),
            ("maxDrawdownTolerancePct", 4),
        ):
            payload = _payload()
            payload[field] = invalid
            response = client.put(
                "/api/v1/user/profile/preferences",
                headers=_headers(token),
                json=payload,
            )
            assert response.status_code == 422, (field, invalid, response.text)

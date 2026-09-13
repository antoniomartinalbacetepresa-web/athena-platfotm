from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app
from app.services.user_personalization_service import UserPersonalizationService


TEST_SECRET = "athena-test-secret-that-is-at-least-32-bytes-long"
TEST_PROFILE_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
PASSWORD = "correct horse battery staple"


def _configure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena_personalization.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", TEST_SECRET)
    monkeypatch.setenv("ATHENA_PROFILE_ENCRYPTION_KEY", TEST_PROFILE_KEY)


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


def _preferences(*, capital: float = 25_000.0, currency: str = "EUR") -> dict[str, object]:
    return {
        "riskTolerance": "balanced",
        "investmentHorizonYears": 12,
        "baseCurrency": currency,
        "objective": "long_term_growth",
        "experienceLevel": "advanced",
        "liquidityNeed": "medium",
        "maxDrawdownTolerancePct": 25,
        "availableCapital": capital,
    }


def test_projection_is_deterministic_and_excludes_sensitive_monetary_values() -> None:
    service = UserPersonalizationService()
    first = service.build(_preferences(capital=25_000.0, currency="EUR"))
    second = service.build(_preferences(capital=900_000_000.0, currency="USD"))

    assert first == second
    serialized = repr(first)
    assert "25000" not in serialized
    assert "900000000" not in serialized
    assert "EUR" not in serialized
    assert "USD" not in serialized
    assert first["policy"] == {
        "presentationOnly": True,
        "recommendationScoringInfluence": False,
        "canonicalWeightingInfluence": False,
        "automaticLearningPromotion": False,
        "automaticTrading": False,
        "sensitiveValuesIncluded": False,
    }


def test_relevant_presentation_preference_changes_fingerprint() -> None:
    service = UserPersonalizationService()
    baseline = _preferences()
    changed = dict(baseline)
    changed["experienceLevel"] = "beginner"

    first = service.build(baseline)
    second = service.build(changed)

    assert first["fingerprint"] != second["fingerprint"]
    assert first["presentation"]["detailLevel"] == "technical"
    assert second["presentation"]["detailLevel"] == "guided"


def test_personalization_requires_authentication(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/user/profile/personalization")
    assert response.status_code == 401


def test_personalization_is_owner_scoped_and_contains_no_raw_sensitive_fields(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token_a = _register_and_token(client, email="personalization-a@example.com")
        token_b = _register_and_token(client, email="personalization-b@example.com")

        stored = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token_a),
            json=_preferences(),
        )
        assert stored.status_code == 200, stored.text

        own = client.get(
            "/api/v1/user/profile/personalization",
            headers=_headers(token_a),
        )
        foreign = client.get(
            "/api/v1/user/profile/personalization",
            headers=_headers(token_b),
        )

    assert own.status_code == 200, own.text
    assert own.json()["status"] == "configured"
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == {"status": "not_configured", "data": None}

    data = own.json()["data"]
    assert data["policy"]["presentationOnly"] is True
    assert data["policy"]["recommendationScoringInfluence"] is False
    assert data["policy"]["canonicalWeightingInfluence"] is False
    assert data["policy"]["automaticLearningPromotion"] is False
    assert data["policy"]["automaticTrading"] is False
    assert "availableCapital" not in repr(data)
    assert "baseCurrency" not in repr(data)
    assert "email" not in repr(data).lower()
    assert "owner" not in repr(data).lower()


def test_capital_only_update_preserves_api_fingerprint(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="capital-invariant@example.com")
        first_put = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=_preferences(capital=10_000.0, currency="EUR"),
        )
        assert first_put.status_code == 200, first_put.text
        first = client.get(
            "/api/v1/user/profile/personalization",
            headers=_headers(token),
        )
        assert first.status_code == 200, first.text

        second_put = client.put(
            "/api/v1/user/profile/preferences",
            headers=_headers(token),
            json=_preferences(capital=500_000.0, currency="USD"),
        )
        assert second_put.status_code == 200, second_put.text
        second = client.get(
            "/api/v1/user/profile/personalization",
            headers=_headers(token),
        )
        assert second.status_code == 200, second.text

    assert first.json()["data"]["fingerprint"] == second.json()["data"]["fingerprint"]

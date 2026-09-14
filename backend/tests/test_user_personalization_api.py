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


def test_readiness_requires_authentication(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/user/profile/personalization/readiness")
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


def test_richer_questionnaire_acceptance_covers_readiness_adaptation_privacy_and_delete(
    monkeypatch, tmp_path
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _register_and_token(client, email="adaptive-acceptance@example.com")
        headers = _headers(token)

        empty = client.get(
            "/api/v1/user/profile/personalization/readiness",
            headers=headers,
        )
        assert empty.status_code == 200, empty.text
        empty_body = empty.json()
        assert empty_body["completionRatio"] == 0.0
        assert empty_body["optionalContextComplete"] is False

        legacy = _preferences()
        legacy.pop("experienceLevel")
        legacy.pop("liquidityNeed")
        legacy.pop("maxDrawdownTolerancePct")
        saved_legacy = client.put(
            "/api/v1/user/profile/preferences",
            headers=headers,
            json=legacy,
        )
        assert saved_legacy.status_code == 200, saved_legacy.text
        partial = client.get(
            "/api/v1/user/profile/personalization/readiness",
            headers=headers,
        )
        assert partial.status_code == 200, partial.text
        partial_body = partial.json()
        assert partial_body["completionRatio"] == 4 / 7
        assert partial_body["missingFields"] == [
            "experienceLevel",
            "liquidityNeed",
            "maxDrawdownTolerancePct",
        ]

        richer = _preferences(capital=321_654.75, currency="EUR")
        richer.update(
            {
                "riskTolerance": "conservative",
                "investmentHorizonYears": 2,
                "objective": "capital_preservation",
                "experienceLevel": "beginner",
                "liquidityNeed": "high",
                "maxDrawdownTolerancePct": 10,
            }
        )
        saved = client.put(
            "/api/v1/user/profile/preferences",
            headers=headers,
            json=richer,
        )
        assert saved.status_code == 200, saved.text

        ready = client.get(
            "/api/v1/user/profile/personalization/readiness",
            headers=headers,
        )
        projection = client.get(
            "/api/v1/user/profile/personalization",
            headers=headers,
        )
        assert ready.status_code == 200, ready.text
        assert projection.status_code == 200, projection.text

        ready_body = ready.json()
        assert ready_body == {
            "status": "diagnostic_only",
            "configuredFields": [
                "riskTolerance",
                "investmentHorizonYears",
                "baseCurrency",
                "objective",
                "experienceLevel",
                "liquidityNeed",
                "maxDrawdownTolerancePct",
            ],
            "missingFields": [],
            "completionRatio": 1.0,
            "optionalContextComplete": True,
            "automaticRecommendationOverrides": False,
            "productionEligible": False,
            "automaticTrading": False,
        }
        assert "321654" not in repr(ready_body)
        assert "EUR" not in repr(ready_body)

        data = projection.json()["data"]
        assert data["presentation"] == {
            "detailLevel": "guided",
            "explanationStyle": "plain_language",
            "riskEmphasis": "high",
            "horizonEmphasis": "short_term",
            "liquidityEmphasis": "high",
            "objectiveFocus": "capital_preservation",
        }
        assert data["policy"] == {
            "presentationOnly": True,
            "recommendationScoringInfluence": False,
            "canonicalWeightingInfluence": False,
            "automaticLearningPromotion": False,
            "automaticTrading": False,
            "sensitiveValuesIncluded": False,
        }
        serialized = repr(data)
        assert "321654" not in serialized
        assert "EUR" not in serialized
        assert "availableCapital" not in serialized
        assert "baseCurrency" not in serialized

        deleted = client.delete(
            "/api/v1/user/profile/preferences",
            headers=headers,
        )
        assert deleted.status_code == 204, deleted.text
        after_delete = client.get(
            "/api/v1/user/profile/personalization/readiness",
            headers=headers,
        )
        personalization_after_delete = client.get(
            "/api/v1/user/profile/personalization",
            headers=headers,
        )

    assert after_delete.status_code == 200, after_delete.text
    assert after_delete.json()["completionRatio"] == 0.0
    assert after_delete.json()["optionalContextComplete"] is False
    assert personalization_after_delete.status_code == 200
    assert personalization_after_delete.json() == {
        "status": "not_configured",
        "data": None,
    }

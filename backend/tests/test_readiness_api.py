from fastapi.testclient import TestClient

from app.api import readiness as readiness_api
from app.main import app


client = TestClient(app)


def test_readiness_endpoint_returns_diagnostics(monkeypatch) -> None:
    expected = {
        "status": "athena_readiness_diagnostics",
        "asOf": "2026-09-10T10:00:00+00:00",
        "operationalReadiness": {
            "completionPercent": 40.0,
            "ready": False,
            "blockers": ["market_history_missing"],
        },
        "automaticActivation": False,
    }

    monkeypatch.setattr(
        readiness_api,
        "build_readiness_report",
        lambda: expected,
    )

    response = client.get("/api/v1/readiness")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["automaticActivation"] is False


def test_readiness_endpoint_is_get_only(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness_api,
        "build_readiness_report",
        lambda: {
            "status": "athena_readiness_diagnostics",
            "automaticActivation": False,
        },
    )

    response = client.post("/api/v1/readiness")

    assert response.status_code == 405

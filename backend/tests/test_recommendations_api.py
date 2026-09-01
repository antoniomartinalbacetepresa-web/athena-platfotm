from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


class FakeLearningStatusService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get_status(
        self,
        *,
        as_of: datetime,
        model_version: str | None = None,
        horizon_days: int | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "as_of": as_of,
                "model_version": model_version,
                "horizon_days": horizon_days,
            }
        )
        return {
            "status": "learning_diagnostics_only",
            "automaticModelMutation": False,
        }


def test_learning_status_endpoint_forwards_explicit_filters(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={
            "as_of": "2026-09-01T20:30:00+00:00",
            "modelVersion": "athena-v1",
            "horizonDays": 90,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "learning_diagnostics_only",
            "automaticModelMutation": False,
        }
    }
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model_version"] == "athena-v1"
    assert call["horizon_days"] == 90
    assert isinstance(call["as_of"], datetime)
    assert call["as_of"].utcoffset() is not None


def test_learning_status_endpoint_uses_timezone_aware_now(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/recommendations/learning/status")

    assert response.status_code == 200
    assert len(fake.calls) == 1
    as_of = fake.calls[0]["as_of"]
    assert isinstance(as_of, datetime)
    assert as_of.utcoffset() is not None


def test_learning_status_endpoint_rejects_naive_as_of(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={"as_of": "2026-09-01T20:30:00"},
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_learning_status_endpoint_rejects_non_positive_horizon(monkeypatch) -> None:
    fake = FakeLearningStatusService()
    monkeypatch.setattr(recommendations, "learning_status_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/status",
        params={"horizonDays": 0},
    )

    assert response.status_code == 422
    assert fake.calls == []

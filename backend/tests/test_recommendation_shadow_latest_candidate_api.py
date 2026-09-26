from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


class FakeLatestCandidateService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[datetime] = []

    def resolve(self, *, as_of: datetime) -> dict[str, object]:
        self.calls.append(as_of)
        return self.payload


def _safe_payload(candidate: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": (
            "shadow_candidate_available_non_advisory"
            if candidate is not None
            else "no_shadow_candidate_known_at_cutoff"
        ),
        "asOf": "2026-09-01T12:00:00+00:00",
        "candidate": candidate,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticTrading": False,
    }


def _candidate() -> dict[str, object]:
    return {
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": "1" * 64,
        "confirmationEvidenceFingerprint": "a" * 64,
        "symbol": "AAPL",
        "asOf": "2026-09-01T11:00:00+00:00",
        "horizons": {
            "30": {
                "horizonDays": 30,
                "expectedExcessReturn": 0.015,
                "explanation": {"contributions": {"technicalScore": 0.01}},
            }
        },
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "action": None,
        "score": None,
        "conviction": None,
    }


def test_latest_shadow_candidate_endpoint_exposes_only_non_advisory_artifact(
    monkeypatch,
) -> None:
    fake = FakeLatestCandidateService(_safe_payload(_candidate()))
    monkeypatch.setattr(recommendations, "latest_shadow_candidate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/shadow/latest-candidate",
        params={"as_of": "2026-09-01T12:00:00+00:00"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["candidate"]["symbol"] == "AAPL"
    assert data["candidate"]["action"] is None
    assert data["candidate"]["score"] is None
    assert data["candidate"]["conviction"] is None
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["automaticTrading"] is False
    assert len(fake.calls) == 1
    assert fake.calls[0].utcoffset() is not None


def test_latest_shadow_candidate_endpoint_rejects_naive_cutoff(monkeypatch) -> None:
    fake = FakeLatestCandidateService(_safe_payload())
    monkeypatch.setattr(recommendations, "latest_shadow_candidate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/shadow/latest-candidate",
        params={"as_of": "2026-09-01T12:00:00"},
    )

    assert response.status_code == 400
    assert fake.calls == []


def test_latest_shadow_candidate_endpoint_blocks_productive_escape(monkeypatch) -> None:
    payload = _safe_payload()
    payload["productionEligible"] = True
    fake = FakeLatestCandidateService(payload)
    monkeypatch.setattr(recommendations, "latest_shadow_candidate_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/recommendations/shadow/latest-candidate")

    assert response.status_code == 500
    assert "contrato de seguridad" in response.json()["detail"]


def test_latest_shadow_candidate_endpoint_blocks_action_in_shadow_artifact(
    monkeypatch,
) -> None:
    candidate = _candidate()
    candidate["action"] = "buy"
    fake = FakeLatestCandidateService(_safe_payload(candidate))
    monkeypatch.setattr(recommendations, "latest_shadow_candidate_service", fake)
    client = TestClient(app)

    response = client.get("/api/v1/recommendations/shadow/latest-candidate")

    assert response.status_code == 500
    assert "convertirse en recomendación" in response.json()["detail"]

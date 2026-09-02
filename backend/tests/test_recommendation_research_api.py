from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendation_research
from app.main import app


class FakeResearchPipelineService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        policy_production_eligibility=False,
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.policy_production_eligibility = policy_production_eligibility
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_research_pipeline_evaluated",
            "researchStageEligible": False,
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "policy": {
                "productionEligibility": self.policy_production_eligibility,
            },
        }


def test_endpoint_runs_default_horizons_and_preserves_no_advice_contract(monkeypatch):
    fake = FakeResearchPipelineService()
    monkeypatch.setattr(recommendation_research, "research_pipeline_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-research-readiness",
        params={"as_of": "2026-09-02T02:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["productionEligible"] is False
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert fake.calls[0]["horizons"] == (7, 30, 90, 180, 365)
    assert fake.calls[0]["as_of"].utcoffset() is not None


def test_endpoint_accepts_explicit_unique_positive_horizons(monkeypatch):
    fake = FakeResearchPipelineService()
    monkeypatch.setattr(recommendation_research, "research_pipeline_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-research-readiness",
        params={"horizons": "7,30,90"},
    )

    assert response.status_code == 200
    assert fake.calls[0]["horizons"] == (7, 30, 90)


def test_endpoint_rejects_naive_as_of_before_calling_service(monkeypatch):
    fake = FakeResearchPipelineService()
    monkeypatch.setattr(recommendation_research, "research_pipeline_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-research-readiness",
        params={"as_of": "2026-09-02T02:00:00"},
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_endpoint_rejects_invalid_horizon_lists_before_calling_service(monkeypatch):
    fake = FakeResearchPipelineService()
    monkeypatch.setattr(recommendation_research, "research_pipeline_service", fake)
    client = TestClient(app)

    for value in ("", "0,30", "30,30", "7,abc"):
        response = client.get(
            "/api/v1/recommendations/learning/shadow-research-readiness",
            params={"horizons": value},
        )
        assert response.status_code == 400

    assert fake.calls == []


def test_endpoint_fails_closed_on_any_production_or_advice_contract_violation(monkeypatch):
    client = TestClient(app)

    for fake in (
        FakeResearchPipelineService(production_eligible=True),
        FakeResearchPipelineService(advisory_status="buy"),
        FakeResearchPipelineService(policy_production_eligibility=True),
    ):
        monkeypatch.setattr(recommendation_research, "research_pipeline_service", fake)
        response = client.get(
            "/api/v1/recommendations/learning/shadow-research-readiness"
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1

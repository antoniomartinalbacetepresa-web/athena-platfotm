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


class FakeLongitudinalService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        recommendation_candidate_ready=False,
        calibration_eligible=False,
        action=None,
        model_version_pooling="forbidden_metrics_partitioned_by_frozen_model_fingerprint",
        automatic_model_mutation=False,
        automatic_production_promotion=False,
        automatic_trading=False,
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.recommendation_candidate_ready = recommendation_candidate_ready
        self.calibration_eligible = calibration_eligible
        self.action = action
        self.model_version_pooling = model_version_pooling
        self.automatic_model_mutation = automatic_model_mutation
        self.automatic_production_promotion = automatic_production_promotion
        self.automatic_trading = automatic_trading
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_live_longitudinal_evidence_pending",
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "actionThresholdCalibrationResearchEligible": self.calibration_eligible,
            "action": self.action,
            "policy": {
                "modelVersionPooling": self.model_version_pooling,
                "automaticModelMutation": self.automatic_model_mutation,
                "automaticProductionPromotion": self.automatic_production_promotion,
                "automaticTrading": self.automatic_trading,
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


def test_longitudinal_endpoint_passes_symbol_as_of_and_horizons(monkeypatch):
    fake = FakeLongitudinalService()
    monkeypatch.setattr(recommendation_research, "live_longitudinal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-live-longitudinal",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-02T02:00:00+00:00",
            "horizons": "7,30,90",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert fake.calls[0]["symbol"] == "AAPL"
    assert fake.calls[0]["horizons"] == (7, 30, 90)
    assert fake.calls[0]["as_of"].utcoffset() is not None


def test_longitudinal_endpoint_rejects_naive_as_of_before_service(monkeypatch):
    fake = FakeLongitudinalService()
    monkeypatch.setattr(recommendation_research, "live_longitudinal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-live-longitudinal",
        params={"as_of": "2026-09-02T02:00:00"},
    )

    assert response.status_code == 400
    assert fake.calls == []


def test_longitudinal_endpoint_fails_closed_on_promotion_or_action_attempt(monkeypatch):
    client = TestClient(app)
    violations = (
        FakeLongitudinalService(advisory_status="buy"),
        FakeLongitudinalService(production_eligible=True),
        FakeLongitudinalService(recommendation_candidate_ready=True),
        FakeLongitudinalService(calibration_eligible=True),
        FakeLongitudinalService(action="buy"),
        FakeLongitudinalService(model_version_pooling="pooled"),
        FakeLongitudinalService(automatic_model_mutation=True),
        FakeLongitudinalService(automatic_production_promotion=True),
        FakeLongitudinalService(automatic_trading=True),
    )

    for fake in violations:
        monkeypatch.setattr(recommendation_research, "live_longitudinal_service", fake)
        response = client.get(
            "/api/v1/recommendations/learning/shadow-live-longitudinal"
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1

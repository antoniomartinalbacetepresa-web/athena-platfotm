from fastapi.testclient import TestClient

from app.api import recommendation_research
from app.main import app


class FakeDecisionResearchService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        recommendation_candidate_ready=False,
        calibration_eligible=False,
        action=None,
        score=None,
        conviction=None,
        action_thresholds="not_fit",
        policy_score="not_calibrated",
        policy_conviction="not_calibrated",
        automatic_production_promotion=False,
        automatic_trading=False,
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.recommendation_candidate_ready = recommendation_candidate_ready
        self.calibration_eligible = calibration_eligible
        self.action = action
        self.score = score
        self.conviction = conviction
        self.action_thresholds = action_thresholds
        self.policy_score = policy_score
        self.policy_conviction = policy_conviction
        self.automatic_production_promotion = automatic_production_promotion
        self.automatic_trading = automatic_trading
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_live_decision_research_ready",
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "actionThresholdCalibrationResearchEligible": self.calibration_eligible,
            "action": self.action,
            "score": self.score,
            "conviction": self.conviction,
            "policy": {
                "actionThresholds": self.action_thresholds,
                "score": self.policy_score,
                "conviction": self.policy_conviction,
                "automaticProductionPromotion": self.automatic_production_promotion,
                "automaticTrading": self.automatic_trading,
            },
        }


def test_decision_research_endpoint_exposes_only_shadow_diagnostics(monkeypatch):
    fake = FakeDecisionResearchService()
    monkeypatch.setattr(
        recommendation_research,
        "live_decision_research_service",
        fake,
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-live-decision-research",
        params={"candidate_id": 17},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["recommendationCandidateReady"] is False
    assert data["action"] is None
    assert data["score"] is None
    assert data["conviction"] is None
    assert fake.calls == [{"candidate_id": 17}]


def test_decision_research_endpoint_rejects_non_positive_candidate_id(monkeypatch):
    fake = FakeDecisionResearchService()
    monkeypatch.setattr(
        recommendation_research,
        "live_decision_research_service",
        fake,
    )
    client = TestClient(app)

    for candidate_id in (0, -1):
        response = client.get(
            "/api/v1/recommendations/learning/shadow-live-decision-research",
            params={"candidate_id": candidate_id},
        )
        assert response.status_code == 422

    assert fake.calls == []


def test_decision_research_endpoint_maps_service_validation_to_400(monkeypatch):
    class InvalidCandidateService:
        def build(self, **kwargs):
            raise ValueError("El candidato shadow live no existe.")

    monkeypatch.setattr(
        recommendation_research,
        "live_decision_research_service",
        InvalidCandidateService(),
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-live-decision-research",
        params={"candidate_id": 99},
    )

    assert response.status_code == 400
    assert "no existe" in response.json()["detail"]


def test_decision_research_endpoint_fails_closed_on_any_promotion_attempt(monkeypatch):
    client = TestClient(app)
    violations = (
        FakeDecisionResearchService(advisory_status="buy"),
        FakeDecisionResearchService(production_eligible=True),
        FakeDecisionResearchService(recommendation_candidate_ready=True),
        FakeDecisionResearchService(calibration_eligible=True),
        FakeDecisionResearchService(action="buy"),
        FakeDecisionResearchService(score=0.8),
        FakeDecisionResearchService(conviction=0.9),
        FakeDecisionResearchService(action_thresholds="fit"),
        FakeDecisionResearchService(policy_score="calibrated"),
        FakeDecisionResearchService(policy_conviction="calibrated"),
        FakeDecisionResearchService(automatic_production_promotion=True),
        FakeDecisionResearchService(automatic_trading=True),
    )

    for fake in violations:
        monkeypatch.setattr(
            recommendation_research,
            "live_decision_research_service",
            fake,
        )
        response = client.get(
            "/api/v1/recommendations/learning/shadow-live-decision-research",
            params={"candidate_id": 3},
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1

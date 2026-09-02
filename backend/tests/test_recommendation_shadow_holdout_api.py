from fastapi.testclient import TestClient

from app.api import recommendation_research
from app.main import app


class FakeHoldoutSealService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        automatic_promotion=False,
        actions="not_assigned",
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.automatic_promotion = automatic_promotion
        self.actions = actions
        self.calls = []

    def evaluate_and_seal(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_independent_holdout_sealed",
            "holdoutSealed": True,
            "actionThresholdCalibrationResearchEligible": False,
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "policy": {
                "automaticProductionPromotion": self.automatic_promotion,
                "actions": self.actions,
            },
        }


def test_holdout_endpoint_runs_default_horizons_and_preserves_shadow_contract(monkeypatch):
    fake = FakeHoldoutSealService()
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness",
        params={"as_of": "2026-09-02T06:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["productionEligible"] is False
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert fake.calls[0]["horizons"] == (7, 30, 90, 180, 365)
    assert fake.calls[0]["as_of"].utcoffset() is not None


def test_holdout_endpoint_rejects_invalid_input_before_calling_service(monkeypatch):
    fake = FakeHoldoutSealService()
    monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
    client = TestClient(app)

    for params in (
        {"as_of": "2026-09-02T06:00:00"},
        {"horizons": ""},
        {"horizons": "0,30"},
        {"horizons": "30,30"},
        {"horizons": "7,abc"},
    ):
        response = client.get(
            "/api/v1/recommendations/learning/shadow-holdout-readiness",
            params=params,
        )
        assert response.status_code == 400

    assert fake.calls == []


def test_holdout_endpoint_fails_closed_on_production_advice_or_policy_violation(monkeypatch):
    client = TestClient(app)

    for fake in (
        FakeHoldoutSealService(production_eligible=True),
        FakeHoldoutSealService(advisory_status="buy"),
        FakeHoldoutSealService(automatic_promotion=True),
        FakeHoldoutSealService(actions="buy"),
    ):
        monkeypatch.setattr(recommendation_research, "holdout_seal_service", fake)
        response = client.get(
            "/api/v1/recommendations/learning/shadow-holdout-readiness"
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1


def test_holdout_endpoint_maps_service_validation_to_400(monkeypatch):
    class RejectingService:
        def evaluate_and_seal(self, **kwargs):
            raise ValueError("cohorte inconsistente")

    monkeypatch.setattr(
        recommendation_research, "holdout_seal_service", RejectingService()
    )
    response = TestClient(app).get(
        "/api/v1/recommendations/learning/shadow-holdout-readiness"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "cohorte inconsistente"

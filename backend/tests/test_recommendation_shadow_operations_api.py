from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import recommendation_shadow_operations
from app.main import app


class FakePreHoldoutPipelineService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        automatic_production_promotion=False,
        actions="not_assigned",
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.automatic_production_promotion = automatic_production_promotion
        self.actions = actions
        self.calls = []

    def prepare(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_pre_holdout_candidates_frozen_and_persisted",
            "preparedHorizonCount": 2,
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "policy": {
                "automaticProductionPromotion": self.automatic_production_promotion,
                "actions": self.actions,
            },
        }


class FakeOperationalLiveCycleService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        recommendation_candidate_ready=False,
        automatic_trading=False,
        automatic_production_promotion=False,
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.recommendation_candidate_ready = recommendation_candidate_ready
        self.automatic_trading = automatic_trading
        self.automatic_production_promotion = automatic_production_promotion
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_live_cycle_persisted",
            "candidateId": 10,
            "candidateFingerprint": "a" * 64,
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "policy": {
                "automaticTrading": self.automatic_trading,
                "automaticProductionPromotion": self.automatic_production_promotion,
            },
        }


class FakeFollowupBatchService:
    def __init__(
        self,
        *,
        advisory_status="no_advice",
        production_eligible=False,
        recommendation_candidate_ready=False,
        automatic_trading=False,
        automatic_production_promotion=False,
    ):
        self.advisory_status = advisory_status
        self.production_eligible = production_eligible
        self.recommendation_candidate_ready = recommendation_candidate_ready
        self.automatic_trading = automatic_trading
        self.automatic_production_promotion = automatic_production_promotion
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_live_followup_batch_completed",
            "candidateCount": 3,
            "processedCandidateCount": 3,
            "evaluatedHorizonCount": 4,
            "advisoryStatus": self.advisory_status,
            "productionEligible": self.production_eligible,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "policy": {
                "automaticTrading": self.automatic_trading,
                "automaticProductionPromotion": self.automatic_production_promotion,
            },
        }


def test_prepare_endpoint_runs_real_research_gated_persistence_defaults(monkeypatch):
    fake = FakePreHoldoutPipelineService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "pre_holdout_pipeline_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-prepare-cohort",
        params={"as_of": "2026-09-04T05:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["preparedHorizonCount"] == 2
    assert fake.calls[0]["horizons"] == (7, 30, 90, 180, 365)
    assert fake.calls[0]["as_of"].utcoffset() is not None
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert response.json()["data"]["productionEligible"] is False


def test_prepare_endpoint_accepts_explicit_unique_positive_horizons(monkeypatch):
    fake = FakePreHoldoutPipelineService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "pre_holdout_pipeline_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-prepare-cohort",
        params={"horizons": "7,30,90"},
    )

    assert response.status_code == 200
    assert fake.calls[0]["horizons"] == (7, 30, 90)


def test_prepare_endpoint_rejects_naive_as_of_and_invalid_horizons_before_service(monkeypatch):
    fake = FakePreHoldoutPipelineService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "pre_holdout_pipeline_service",
        fake,
    )
    client = TestClient(app)

    naive = client.post(
        "/api/v1/recommendations/learning/shadow-prepare-cohort",
        params={"as_of": "2026-09-04T05:00:00"},
    )
    assert naive.status_code == 400

    for value in ("", "0,30", "30,30", "30,abc"):
        response = client.post(
            "/api/v1/recommendations/learning/shadow-prepare-cohort",
            params={"horizons": value},
        )
        assert response.status_code == 400

    assert fake.calls == []


def test_prepare_endpoint_fails_closed_on_advice_production_or_action_escalation(monkeypatch):
    client = TestClient(app)
    violations = (
        FakePreHoldoutPipelineService(advisory_status="buy"),
        FakePreHoldoutPipelineService(production_eligible=True),
        FakePreHoldoutPipelineService(automatic_production_promotion=True),
        FakePreHoldoutPipelineService(actions="buy"),
    )

    for fake in violations:
        monkeypatch.setattr(
            recommendation_shadow_operations,
            "pre_holdout_pipeline_service",
            fake,
        )
        response = client.post(
            "/api/v1/recommendations/learning/shadow-prepare-cohort"
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1


def test_post_endpoint_runs_operational_cycle_with_real_safe_defaults(monkeypatch):
    fake = FakeOperationalLiveCycleService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "operational_live_cycle_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-live-cycle",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-04T05:00:00+00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["candidateId"] == 10
    assert fake.calls == [
        {
            "symbol": "AAPL",
            "as_of": fake.calls[0]["as_of"],
            "benchmark_symbol": "SPY",
            "horizons": (7, 30, 90, 180, 365),
        }
    ]
    assert fake.calls[0]["as_of"].utcoffset() is not None
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert response.json()["data"]["productionEligible"] is False
    assert response.json()["data"]["recommendationCandidateReady"] is False


def test_endpoint_accepts_explicit_horizons_and_benchmark(monkeypatch):
    fake = FakeOperationalLiveCycleService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "operational_live_cycle_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-live-cycle",
        params={
            "symbol": "MSFT",
            "benchmark_symbol": "QQQ",
            "horizons": "30,90",
        },
    )

    assert response.status_code == 200
    assert fake.calls[0]["benchmark_symbol"] == "QQQ"
    assert fake.calls[0]["horizons"] == (30, 90)


def test_endpoint_rejects_naive_as_of_and_invalid_horizons_before_service(monkeypatch):
    fake = FakeOperationalLiveCycleService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "operational_live_cycle_service",
        fake,
    )
    client = TestClient(app)

    naive = client.post(
        "/api/v1/recommendations/learning/shadow-live-cycle",
        params={"symbol": "AAPL", "as_of": "2026-09-04T05:00:00"},
    )
    assert naive.status_code == 400

    for value in ("", "0,30", "30,30", "30,abc"):
        response = client.post(
            "/api/v1/recommendations/learning/shadow-live-cycle",
            params={"symbol": "AAPL", "horizons": value},
        )
        assert response.status_code == 400

    assert fake.calls == []


def test_endpoint_fails_closed_on_shadow_or_automation_policy_escalation(monkeypatch):
    client = TestClient(app)
    violations = (
        FakeOperationalLiveCycleService(advisory_status="buy"),
        FakeOperationalLiveCycleService(production_eligible=True),
        FakeOperationalLiveCycleService(recommendation_candidate_ready=True),
        FakeOperationalLiveCycleService(automatic_trading=True),
        FakeOperationalLiveCycleService(automatic_production_promotion=True),
    )

    for fake in violations:
        monkeypatch.setattr(
            recommendation_shadow_operations,
            "operational_live_cycle_service",
            fake,
        )
        response = client.post(
            "/api/v1/recommendations/learning/shadow-live-cycle",
            params={"symbol": "AAPL"},
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1


def test_endpoint_maps_validation_errors_without_leaking_as_server_success(monkeypatch):
    class RejectingService(FakeOperationalLiveCycleService):
        def run(self, **kwargs):
            self.calls.append(kwargs)
            raise ValueError("cohorte frozen inválida")

    fake = RejectingService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "operational_live_cycle_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-live-cycle",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 400
    assert "cohorte frozen inválida" in response.json()["detail"]


def test_followup_endpoint_processes_all_persisted_candidates_with_safe_defaults(monkeypatch):
    fake = FakeFollowupBatchService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "followup_batch_service",
        fake,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/learning/shadow-followup-cycle",
        params={"as_of": "2026-09-04T06:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["processedCandidateCount"] == 3
    assert response.json()["data"]["evaluatedHorizonCount"] == 4
    assert fake.calls[0]["horizons"] == (7, 30, 90, 180, 365)
    assert fake.calls[0]["as_of"].utcoffset() is not None
    assert response.json()["data"]["advisoryStatus"] == "no_advice"
    assert response.json()["data"]["productionEligible"] is False
    assert response.json()["data"]["recommendationCandidateReady"] is False


def test_followup_endpoint_rejects_naive_cutoff_and_invalid_horizons(monkeypatch):
    fake = FakeFollowupBatchService()
    monkeypatch.setattr(
        recommendation_shadow_operations,
        "followup_batch_service",
        fake,
    )
    client = TestClient(app)

    naive = client.post(
        "/api/v1/recommendations/learning/shadow-followup-cycle",
        params={"as_of": "2026-09-04T06:00:00"},
    )
    assert naive.status_code == 400

    for value in ("", "0,30", "30,30", "30,abc"):
        response = client.post(
            "/api/v1/recommendations/learning/shadow-followup-cycle",
            params={"horizons": value},
        )
        assert response.status_code == 400

    assert fake.calls == []


def test_followup_endpoint_fails_closed_on_shadow_or_automation_escalation(monkeypatch):
    client = TestClient(app)
    violations = (
        FakeFollowupBatchService(advisory_status="buy"),
        FakeFollowupBatchService(production_eligible=True),
        FakeFollowupBatchService(recommendation_candidate_ready=True),
        FakeFollowupBatchService(automatic_trading=True),
        FakeFollowupBatchService(automatic_production_promotion=True),
    )

    for fake in violations:
        monkeypatch.setattr(
            recommendation_shadow_operations,
            "followup_batch_service",
            fake,
        )
        response = client.post(
            "/api/v1/recommendations/learning/shadow-followup-cycle"
        )
        assert response.status_code == 500
        assert len(fake.calls) == 1

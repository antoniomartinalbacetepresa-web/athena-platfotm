from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api import recommendation_market_factor_exposure as api_module
from app.main import app


client = TestClient(app)
AS_OF = datetime(2026, 1, 22, tzinfo=timezone.utc)
KEY = "b" * 64


class FakeService:
    def evaluate(self, **kwargs: object) -> dict[str, object]:
        return {
            "module": "pit_price_factor_exposure",
            "instrumentId": 1,
            "sourceProvider": "test",
            "periodStart": "2026-01-01T00:00:00+00:00",
            "periodEnd": "2026-01-21T00:00:00+00:00",
            "asOf": AS_OF.isoformat(),
            "availableAt": "2026-01-21T00:00:00+00:00",
            "sampleCount": 20,
            "factors": {"momentum": 0.12, "low_volatility": -0.02},
            "diagnostics": {"realizedVolatilityUnannualized": 0.02, "meanObservedReturn": 0.005},
            "observations": [{} for _ in range(20)],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_and_retrieved_at_lte_as_of",
                "missingFactors": "not_inferred",
                "momentumEstimator": "total_return_first_to_last_pit_price",
                "lowVolatilityEstimator": "negative_sample_standard_deviation_of_observed_returns_unannualized",
                "frequencyNormalization": "not_assumed",
                "thresholds": "not_calibrated",
                "purpose": "factor_risk_diagnostic_only",
            },
            "factorExposureKey": KEY,
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


class FakeRepository:
    def append(self, *, artifact: dict[str, object]) -> dict[str, object]:
        return {"artifact": artifact}


def test_price_factor_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "_price_service", FakeService())
    monkeypatch.setattr(api_module, "_price_repository", FakeRepository())
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/price-factors",
        json={
            "instrumentId": 1,
            "sourceProvider": "test",
            "periodStart": "2026-01-01T00:00:00Z",
            "periodEnd": "2026-01-21T00:00:00Z",
            "asOf": "2026-01-22T00:00:00Z",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["factors"] == {"momentum": 0.12, "low_volatility": -0.02}
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["frequencyNormalization"] == "not_assumed"
    assert data["factorExposureKey"] == KEY


def test_price_factor_endpoint_rejects_naive_asof(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "_price_service", FakeService())
    monkeypatch.setattr(api_module, "_price_repository", FakeRepository())
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/price-factors",
        json={
            "instrumentId": 1,
            "sourceProvider": "test",
            "periodStart": "2026-01-01T00:00:00Z",
            "periodEnd": "2026-01-21T00:00:00Z",
            "asOf": "2026-01-22T00:00:00",
        },
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

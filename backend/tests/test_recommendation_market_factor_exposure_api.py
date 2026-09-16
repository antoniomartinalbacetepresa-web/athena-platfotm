from fastapi.testclient import TestClient

import app.api.recommendation_market_factor_exposure as api_module
from app.main import app


client = TestClient(app)


class FakeService:
    def evaluate(self, **kwargs: object) -> dict[str, object]:
        return {
            "module": "pit_market_beta_exposure",
            "factorExposureKey": "a" * 64,
            "instrumentId": 1,
            "benchmarkInstrumentId": 2,
            "sourceProvider": "test",
            "periodStart": "2026-01-01T00:00:00+00:00",
            "periodEnd": "2026-01-31T00:00:00+00:00",
            "asOf": "2026-02-01T00:00:00+00:00",
            "availableAt": "2026-01-31T00:00:00+00:00",
            "sampleCount": 20,
            "factors": {"market": 1.2},
            "observations": [{} for _ in range(20)],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "observed_and_retrieved_at_lte_as_of",
                "missingFactors": "not_inferred",
                "estimator": "sample_covariance_asset_market_over_sample_variance_market",
            },
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


class FakeRepository:
    def append(self, *, artifact: dict[str, object]) -> dict[str, object]:
        return {"artifact": artifact}


def body() -> dict[str, object]:
    return {
        "instrumentId": 1,
        "benchmarkInstrumentId": 2,
        "sourceProvider": "test",
        "periodStart": "2026-01-01T00:00:00Z",
        "periodEnd": "2026-01-31T00:00:00Z",
        "asOf": "2026-02-01T00:00:00Z",
    }


def test_market_beta_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "_service", FakeService())
    monkeypatch.setattr(api_module, "_repository", FakeRepository())
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/market-beta",
        json=body(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["factorExposureKey"] == "a" * 64
    assert data["factors"] == {"market": 1.2}
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False


def test_market_beta_endpoint_rejects_naive_time_before_engine(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "_service", FakeService())
    monkeypatch.setattr(api_module, "_repository", FakeRepository())
    request = body()
    request["asOf"] = "2026-02-01T00:00:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/market-beta",
        json=request,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

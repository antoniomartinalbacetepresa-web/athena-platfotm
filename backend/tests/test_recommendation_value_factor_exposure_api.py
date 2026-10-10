from fastapi.testclient import TestClient

from app.api import recommendation_fundamental_factor_evidence as api_module
from app.main import app


client = TestClient(app)


class FakeValueService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)

    def validate_artifact(self, artifact):
        return dict(artifact)


class FakeValueRepository:
    def __init__(self):
        self.calls = []

    def append(self, *, artifact):
        self.calls.append(dict(artifact))
        return {"artifact": dict(artifact)}


def payload():
    return {
        "module": "pit_value_factor_exposure",
        "instrumentId": 42,
        "asOf": "2026-03-01T12:00:00+00:00",
        "availableAt": "2026-03-01T12:00:00+00:00",
        "bookToMarket": 0.5,
        "bookToMarketEvidenceKey": "a" * 64,
        "issuerId": 7,
        "cik": "0000123456",
        "universeCount": 20,
        "universeFingerprint": "b" * 64,
        "factors": {"value": 0.25},
        "factorExposureKey": "c" * 64,
        "provenance": {},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "thresholds": "not_calibrated",
        },
    }


def request_body():
    return {"instrumentId": 42, "asOf": "2026-03-01T12:00:00+00:00"}


def test_value_endpoint_returns_persisted_research_only_factor(monkeypatch) -> None:
    service = FakeValueService(payload())
    repository = FakeValueRepository()
    monkeypatch.setattr(api_module, "_value_service", service)
    monkeypatch.setattr(api_module, "_value_repository", repository)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/value",
        json=request_body(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["factors"] == {"value": 0.25}
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert len(repository.calls) == 1


def test_value_endpoint_fails_closed_on_out_of_range_or_unsafe_output(monkeypatch) -> None:
    unsafe_payloads = []
    item = payload()
    item["factors"] = {"value": 1.1}
    unsafe_payloads.append(item)
    item = payload()
    item["productionEligible"] = True
    unsafe_payloads.append(item)
    item = payload()
    item["isWeightingReady"] = True
    unsafe_payloads.append(item)
    item = payload()
    item["policy"] = {**item["policy"], "automaticTrading": True}
    unsafe_payloads.append(item)

    for item in unsafe_payloads:
        monkeypatch.setattr(api_module, "_value_service", FakeValueService(item))
        monkeypatch.setattr(api_module, "_value_repository", FakeValueRepository())
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-exposure/value",
            json=request_body(),
        )
        assert response.status_code == 500


def test_value_endpoint_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = FakeValueService(payload())
    monkeypatch.setattr(api_module, "_value_service", service)
    monkeypatch.setattr(api_module, "_value_repository", FakeValueRepository())
    body = request_body()
    body["asOf"] = "2026-03-01T12:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/value",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_value_endpoint_forbids_free_factor_input_and_is_registered() -> None:
    body = request_body()
    body["value"] = 0.9
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-exposure/value",
        json=body,
    )
    assert response.status_code == 422
    assert (
        "/api/v1/recommendations/professional-research/factor-exposure/value"
        in app.openapi()["paths"]
    )

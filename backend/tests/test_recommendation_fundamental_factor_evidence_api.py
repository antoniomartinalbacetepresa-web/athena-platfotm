from fastapi.testclient import TestClient

from app.api import recommendation_fundamental_factor_evidence as api_module
from app.main import app


client = TestClient(app)


class FakeService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)

    def validate_artifact(self, artifact):
        return dict(artifact)


class FakeRepository:
    def __init__(self):
        self.calls = []

    def append(self, *, artifact):
        self.calls.append(dict(artifact))
        return {"artifact": dict(artifact)}


def resolved_payload():
    return {
        "module": "book_to_market_pit_evidence",
        "status": "resolved",
        "evidenceKey": "a" * 64,
        "instrumentId": 42,
        "asOf": "2026-03-01T12:00:00+00:00",
        "bookEquityUsd": 500.0,
        "marketCapUsd": 1000.0,
        "bookToMarket": 0.5,
        "identityEvidence": {"instrumentId": 42, "identityKey": "b" * 64},
        "fundamentalEvidence": {"evidenceKey": "c" * 64},
        "marketCapEvidence": {"marketCapUsd": 1000.0},
        "factorReady": False,
        "factorExposure": None,
        "policy": {
            "normalization": "not_yet_cross_sectionally_ranked",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
    }


def missing_payload():
    payload = resolved_payload()
    payload.update(
        {
            "status": "missing",
            "evidenceKey": None,
            "bookToMarket": None,
            "missingReason": "stockholders_equity_missing",
        }
    )
    return payload


def request_body():
    return {"instrumentId": 42, "asOf": "2026-03-01T12:00:00+00:00"}


def test_endpoint_returns_and_persists_resolved_research_only_evidence(monkeypatch) -> None:
    service = FakeService(resolved_payload())
    repository = FakeRepository()
    monkeypatch.setattr(api_module, "_service", service)
    monkeypatch.setattr(api_module, "_repository", repository)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market",
        json=request_body(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["bookToMarket"] == 0.5
    assert data["factorReady"] is False
    assert data["factorExposure"] is None
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert len(repository.calls) == 1


def test_endpoint_returns_missing_without_persisting_or_imputing_value(monkeypatch) -> None:
    service = FakeService(missing_payload())
    repository = FakeRepository()
    monkeypatch.setattr(api_module, "_service", service)
    monkeypatch.setattr(api_module, "_repository", repository)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market",
        json=request_body(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "missing"
    assert data["bookToMarket"] is None
    assert repository.calls == []


def test_endpoint_fails_closed_if_raw_ratio_is_presented_as_factor(monkeypatch) -> None:
    payload = resolved_payload()
    payload["factorReady"] = True
    payload["factorExposure"] = 0.5
    monkeypatch.setattr(api_module, "_service", FakeService(payload))
    monkeypatch.setattr(api_module, "_repository", FakeRepository())

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market",
        json=request_body(),
    )

    assert response.status_code == 500
    assert "factor" in response.json()["detail"].lower()


def test_endpoint_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = FakeService(resolved_payload())
    monkeypatch.setattr(api_module, "_service", service)
    monkeypatch.setattr(api_module, "_repository", FakeRepository())
    body = request_body()
    body["asOf"] = "2026-03-01T12:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_endpoint_forbids_extra_fields_and_route_is_registered() -> None:
    body = request_body()
    body["valueScore"] = 0.9
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market",
        json=body,
    )
    assert response.status_code == 422

    assert (
        "/api/v1/recommendations/professional-research/factor-evidence/book-to-market"
        in app.openapi()["paths"]
    )

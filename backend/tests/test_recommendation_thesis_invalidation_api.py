from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_thesis_invalidation as thesis_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"


@dataclass(frozen=True)
class _Result:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Service:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> _Result:
        self.calls.append(kwargs)
        return _Result(self.payload)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "asOf": AS_OF,
        "criteria": [
            {
                "name": "gross_margin_floor",
                "metric": "gross_margin",
                "operator": "lt",
                "threshold": 0.35,
                "observedValue": 0.32,
                "breached": True,
                "availableAt": AVAILABLE_AT,
                "source": "sec_filing",
                "sourceRef": "filing:example#gross-margin",
            }
        ],
        "breachedCount": 1,
        "thesisInvalidationEvidencePresent": True,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "priceOnlyInvalidation": "forbidden",
        },
    }
    payload.update(overrides)
    return payload


def _request() -> dict[str, object]:
    return {
        "symbol": "AAPL",
        "asOf": AS_OF,
        "criteria": [
            {
                "name": "gross_margin_floor",
                "metric": "gross_margin",
                "operator": "lt",
                "threshold": 0.35,
                "observedValue": 0.32,
                "availableAt": AVAILABLE_AT,
                "source": "sec_filing",
                "sourceRef": "filing:example#gross-margin",
            }
        ],
    }


def test_thesis_invalidation_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(thesis_api, "thesis_invalidation_service", service)

    response = client.post(
        "/api/v1/recommendations/professional-research/thesis-invalidation",
        json=_request(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["priceOnlyInvalidation"] == "forbidden"
    assert data["criteria"][0]["sourceRef"] == "filing:example#gross-margin"
    assert len(service.calls) == 1


def test_thesis_invalidation_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    unsafe_payloads = (
        _payload(advisoryStatus="sell"),
        _payload(productionEligible=True),
        _payload(isWeightingReady=True),
        _payload(policy={"automaticTrading": True, "automaticProductionPromotion": False, "priceOnlyInvalidation": "forbidden"}),
        _payload(policy={"automaticTrading": False, "automaticProductionPromotion": True, "priceOnlyInvalidation": "forbidden"}),
        _payload(policy={"automaticTrading": False, "automaticProductionPromotion": False, "priceOnlyInvalidation": "allowed"}),
        _payload(criteria=[{"name": "gross_margin_floor"}]),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(thesis_api, "thesis_invalidation_service", _Service(payload))
        response = client.post(
            "/api/v1/recommendations/professional-research/thesis-invalidation",
            json=_request(),
        )
        assert response.status_code == 500


def test_thesis_invalidation_api_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(thesis_api, "thesis_invalidation_service", service)
    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/thesis-invalidation",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_thesis_invalidation_api_rejects_naive_evidence_timestamp(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(thesis_api, "thesis_invalidation_service", service)
    body = _request()
    body["criteria"][0]["availableAt"] = "2025-12-31T23:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/thesis-invalidation",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []

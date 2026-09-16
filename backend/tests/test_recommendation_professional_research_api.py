from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_professional_research as professional_api
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


def _reverse_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 7,
        "asOf": AS_OF,
        "impliedEpsCagr": 0.12,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "policy": {
            "automaticTrading": False,
            "calibration": "not_productive_until_out_of_sample_validated",
        },
    }
    payload.update(overrides)
    return payload


def _gap_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 7,
        "asOf": AS_OF,
        "impliedEpsCagr": 0.12,
        "referenceExpectation": {
            "kind": "company_guidance",
            "metric": "eps_cagr",
            "horizonYears": 5,
            "epsCagr": 0.15,
            "availableAt": AVAILABLE_AT,
            "source": "sec_company_guidance",
            "sourceRef": "filing:example#guidance",
        },
        "expectationsGap": 0.03,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "crossKindAggregation": "forbidden_until_separately_calibrated",
        },
    }
    payload.update(overrides)
    return payload


def test_reverse_valuation_endpoint_exposes_explicit_research_only_scenario(monkeypatch) -> None:
    service = _Service(_reverse_payload())
    monkeypatch.setattr(professional_api, "reverse_valuation_service", service)

    response = client.get(
        "/api/v1/recommendations/professional-research/reverse-valuation",
        params={
            "symbol": "AAPL",
            "horizonYears": 5,
            "requiredReturn": 0.10,
            "exitPe": 20.0,
            "asOf": AS_OF,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["policy"]["automaticTrading"] is False
    assert len(service.calls) == 1
    assert service.calls[0]["symbol"] == "AAPL"
    assert service.calls[0]["horizon_years"] == 5


def test_expectations_gap_endpoint_preserves_typed_pit_evidence(monkeypatch) -> None:
    service = _Service(_gap_payload())
    monkeypatch.setattr(professional_api, "expectations_gap_service", service)

    response = client.get(
        "/api/v1/recommendations/professional-research/expectations-gap",
        params={
            "symbol": "AAPL",
            "horizonYears": 5,
            "requiredReturn": 0.10,
            "exitPe": 20.0,
            "referenceEpsCagr": 0.15,
            "expectationKind": "company_guidance",
            "expectationMetric": "eps_cagr",
            "expectationHorizonYears": 5,
            "expectationAvailableAt": AVAILABLE_AT,
            "expectationSource": "sec_company_guidance",
            "expectationSourceRef": "filing:example#guidance",
            "asOf": AS_OF,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["referenceExpectation"]["kind"] == "company_guidance"
    assert data["referenceExpectation"]["horizonYears"] == 5
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["automaticProductionPromotion"] is False


def test_professional_research_api_fails_closed_on_unsafe_reverse_contract(monkeypatch) -> None:
    unsafe_payloads = (
        _reverse_payload(advisoryStatus="buy"),
        _reverse_payload(productionEligible=True),
        _reverse_payload(policy={"automaticTrading": True}),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(
            professional_api,
            "reverse_valuation_service",
            _Service(payload),
        )
        response = client.get(
            "/api/v1/recommendations/professional-research/reverse-valuation",
            params={
                "symbol": "AAPL",
                "horizonYears": 5,
                "requiredReturn": 0.10,
                "exitPe": 20.0,
                "asOf": AS_OF,
            },
        )
        assert response.status_code == 500


def test_professional_research_api_fails_closed_on_unsafe_expectations_contract(monkeypatch) -> None:
    unsafe_payloads = (
        _gap_payload(productionEligible=True),
        _gap_payload(isWeightingReady=True),
        _gap_payload(policy={"automaticTrading": True, "automaticProductionPromotion": False}),
        _gap_payload(policy={"automaticTrading": False, "automaticProductionPromotion": True}),
        _gap_payload(referenceExpectation={"kind": "company_guidance"}),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(
            professional_api,
            "expectations_gap_service",
            _Service(payload),
        )
        response = client.get(
            "/api/v1/recommendations/professional-research/expectations-gap",
            params={
                "symbol": "AAPL",
                "horizonYears": 5,
                "requiredReturn": 0.10,
                "exitPe": 20.0,
                "referenceEpsCagr": 0.15,
                "expectationKind": "company_guidance",
                "expectationMetric": "eps_cagr",
                "expectationHorizonYears": 5,
                "expectationAvailableAt": AVAILABLE_AT,
                "expectationSource": "sec_company_guidance",
                "expectationSourceRef": "filing:example#guidance",
                "asOf": AS_OF,
            },
        )
        assert response.status_code == 500


def test_professional_research_api_rejects_naive_as_of_before_service_call(monkeypatch) -> None:
    service = _Service(_reverse_payload())
    monkeypatch.setattr(professional_api, "reverse_valuation_service", service)

    response = client.get(
        "/api/v1/recommendations/professional-research/reverse-valuation",
        params={
            "symbol": "AAPL",
            "horizonYears": 5,
            "requiredReturn": 0.10,
            "exitPe": 20.0,
            "asOf": "2026-01-01T00:00:00",
        },
    )

    assert response.status_code == 400
    assert service.calls == []

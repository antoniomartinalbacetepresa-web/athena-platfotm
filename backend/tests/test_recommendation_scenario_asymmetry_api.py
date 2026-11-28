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


def _payload(**overrides: object) -> dict[str, object]:
    scenarios = [
        {
            "name": "bear",
            "epsCagr": -0.05,
            "exitPe": 12.0,
            "annualizedReturn": -0.12,
            "availableAt": AVAILABLE_AT,
            "source": "research_bear",
            "sourceRef": "scenario:bear:v1",
        },
        {
            "name": "base",
            "epsCagr": 0.10,
            "exitPe": 20.0,
            "annualizedReturn": 0.10,
            "availableAt": AVAILABLE_AT,
            "source": "research_base",
            "sourceRef": "scenario:base:v1",
        },
        {
            "name": "bull",
            "epsCagr": 0.20,
            "exitPe": 28.0,
            "annualizedReturn": 0.28,
            "availableAt": AVAILABLE_AT,
            "source": "research_bull",
            "sourceRef": "scenario:bull:v1",
        },
    ]
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "instrumentId": 7,
        "asOf": AS_OF,
        "scenarios": scenarios,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "probabilities": "not_assigned_no_expected_value_without_calibrated_probabilities",
        },
    }
    payload.update(overrides)
    return payload


def _params() -> dict[str, object]:
    return {
        "symbol": "AAPL",
        "horizonYears": 5,
        "requiredReturn": 0.10,
        "bearEpsCagr": -0.05,
        "bearExitPe": 12.0,
        "bearAvailableAt": AVAILABLE_AT,
        "bearSource": "research_bear",
        "bearSourceRef": "scenario:bear:v1",
        "baseEpsCagr": 0.10,
        "baseExitPe": 20.0,
        "baseAvailableAt": AVAILABLE_AT,
        "baseSource": "research_base",
        "baseSourceRef": "scenario:base:v1",
        "bullEpsCagr": 0.20,
        "bullExitPe": 28.0,
        "bullAvailableAt": AVAILABLE_AT,
        "bullSource": "research_bull",
        "bullSourceRef": "scenario:bull:v1",
        "asOf": AS_OF,
    }


def test_scenario_asymmetry_endpoint_preserves_probability_free_pit_evidence(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(professional_api, "scenario_asymmetry_service", service)

    response = client.get(
        "/api/v1/recommendations/professional-research/scenario-asymmetry",
        params=_params(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert [item["name"] for item in data["scenarios"]] == ["bear", "base", "bull"]
    assert data["policy"]["probabilities"] == "not_assigned_no_expected_value_without_calibrated_probabilities"
    assert data["policy"]["automaticTrading"] is False
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["horizon_years"] == 5
    assert call["bear"].name == "bear"
    assert call["base"].source_ref == "scenario:base:v1"
    assert call["bull"].exit_pe == 28.0


def test_scenario_asymmetry_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    unsafe_payloads = (
        _payload(advisoryStatus="buy"),
        _payload(productionEligible=True),
        _payload(isWeightingReady=True),
        _payload(policy={"automaticTrading": True, "automaticProductionPromotion": False, "probabilities": "not_assigned_no_expected_value_without_calibrated_probabilities"}),
        _payload(policy={"automaticTrading": False, "automaticProductionPromotion": True, "probabilities": "not_assigned_no_expected_value_without_calibrated_probabilities"}),
        _payload(policy={"automaticTrading": False, "automaticProductionPromotion": False, "probabilities": "equal_weighted"}),
        _payload(scenarios=[{"name": "bear"}]),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(professional_api, "scenario_asymmetry_service", _Service(payload))
        response = client.get(
            "/api/v1/recommendations/professional-research/scenario-asymmetry",
            params=_params(),
        )
        assert response.status_code == 500


def test_scenario_asymmetry_api_rejects_naive_as_of_before_service_call(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(professional_api, "scenario_asymmetry_service", service)
    params = _params()
    params["asOf"] = "2026-01-01T00:00:00"

    response = client.get(
        "/api/v1/recommendations/professional-research/scenario-asymmetry",
        params=params,
    )

    assert response.status_code == 400
    assert service.calls == []

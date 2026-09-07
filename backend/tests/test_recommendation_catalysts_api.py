from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_catalysts as catalysts_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
DEFINED_AT = "2025-12-01T00:00:00+00:00"
EXPECTED_START = "2025-12-15T00:00:00+00:00"
EXPECTED_END = "2025-12-31T00:00:00+00:00"
OCCURRED_AT = "2025-12-20T00:00:00+00:00"
OCCURRENCE_AVAILABLE_AT = "2025-12-20T01:00:00+00:00"


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


def _catalyst_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "catalystId": "earnings-q4",
        "name": "Q4 earnings",
        "kind": "earnings",
        "state": "occurred",
        "timeliness": "on_time",
        "expectedStart": EXPECTED_START,
        "expectedEnd": EXPECTED_END,
        "definedAt": DEFINED_AT,
        "definitionSource": "sec_calendar",
        "definitionSourceRef": "calendar:q4",
        "occurredAt": OCCURRED_AT,
        "occurrenceAvailableAt": OCCURRENCE_AVAILABLE_AT,
        "occurrenceSource": "sec_filing",
        "occurrenceSourceRef": "filing:q4",
    }
    payload.update(overrides)
    return payload


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "symbol": "AAPL",
        "asOf": AS_OF,
        "catalysts": [_catalyst_payload()],
        "occurredCount": 1,
        "pendingCount": 0,
        "missedCount": 0,
        "delayedCount": 0,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "missedCatalystAutomaticallyInvalidatesThesis": False,
        },
    }
    payload.update(overrides)
    return payload


def _request() -> dict[str, object]:
    return {
        "symbol": "AAPL",
        "asOf": AS_OF,
        "catalysts": [
            {
                "catalystId": "earnings-q4",
                "name": "Q4 earnings",
                "kind": "earnings",
                "expectedStart": EXPECTED_START,
                "expectedEnd": EXPECTED_END,
                "definedAt": DEFINED_AT,
                "definitionSource": "sec_calendar",
                "definitionSourceRef": "calendar:q4",
                "occurredAt": OCCURRED_AT,
                "occurrenceAvailableAt": OCCURRENCE_AVAILABLE_AT,
                "occurrenceSource": "sec_filing",
                "occurrenceSourceRef": "filing:q4",
            }
        ],
    }


def test_catalysts_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=_request(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["automaticProductionPromotion"] is False
    assert data["policy"]["missedCatalystAutomaticallyInvalidatesThesis"] is False
    assert data["catalysts"][0]["occurrenceSourceRef"] == "filing:q4"
    assert len(service.calls) == 1


def test_catalysts_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    unsafe_payloads = (
        _payload(advisoryStatus="sell"),
        _payload(productionEligible=True),
        _payload(isWeightingReady=True),
        _payload(
            policy={
                "automaticTrading": True,
                "automaticProductionPromotion": False,
                "missedCatalystAutomaticallyInvalidatesThesis": False,
            }
        ),
        _payload(
            policy={
                "automaticTrading": False,
                "automaticProductionPromotion": True,
                "missedCatalystAutomaticallyInvalidatesThesis": False,
            }
        ),
        _payload(
            policy={
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "missedCatalystAutomaticallyInvalidatesThesis": True,
            }
        ),
        _payload(catalysts=[_catalyst_payload(definitionSourceRef="")]),
        _payload(catalysts=[_catalyst_payload(occurrenceSourceRef="")]),
        _payload(catalysts=[_catalyst_payload(state="unknown")]),
        _payload(occurredCount=0),
        _payload(delayedCount=2),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(catalysts_api, "catalyst_service", _Service(payload))
        response = client.post(
            "/api/v1/recommendations/professional-research/catalysts",
            json=_request(),
        )
        assert response.status_code == 500


def test_catalysts_api_rejects_duplicate_output_identity(monkeypatch) -> None:
    first = _catalyst_payload()
    second = _catalyst_payload(name="Duplicate event")
    service = _Service(
        _payload(
            catalysts=[first, second],
            occurredCount=2,
        )
    )
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=_request(),
    )

    assert response.status_code == 500


def test_catalysts_api_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)
    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_catalysts_api_rejects_naive_definition_timestamp_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)
    body = _request()
    body["catalysts"][0]["definedAt"] = "2025-12-01T00:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_catalysts_api_rejects_naive_occurrence_timestamp_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)
    body = _request()
    body["catalysts"][0]["occurrenceAvailableAt"] = "2025-12-20T01:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_catalysts_api_rejects_state_occurrence_mismatch(monkeypatch) -> None:
    service = _Service(
        _payload(
            catalysts=[
                _catalyst_payload(
                    state="missed",
                    timeliness="not_observed_by_expected_end",
                )
            ],
            occurredCount=0,
            missedCount=1,
        )
    )
    monkeypatch.setattr(catalysts_api, "catalyst_service", service)

    response = client.post(
        "/api/v1/recommendations/professional-research/catalysts",
        json=_request(),
    )

    assert response.status_code == 500

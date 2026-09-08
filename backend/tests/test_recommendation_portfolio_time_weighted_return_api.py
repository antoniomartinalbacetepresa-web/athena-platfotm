from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def payload() -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "EUR",
        "asOf": "2026-02-02T00:00:00Z",
        "periodStart": "2026-01-01T00:00:00Z",
        "periodEnd": "2026-02-01T00:00:00Z",
        "segments": [
            {
                "startAt": "2026-01-01T00:00:00Z",
                "endAt": "2026-01-16T00:00:00Z",
                "beginningValue": {
                    "value": 100.0,
                    "observedAt": "2026-01-01T00:00:00Z",
                    "availableAt": "2026-01-01T00:00:00Z",
                    "source": "portfolio_ledger",
                    "sourceRef": "start",
                },
                "endingValueBeforeFlow": {
                    "value": 110.0,
                    "observedAt": "2026-01-16T00:00:00Z",
                    "availableAt": "2026-01-16T00:00:00Z",
                    "source": "portfolio_ledger",
                    "sourceRef": "pre-flow",
                },
                "externalFlowAfterEnd": {
                    "amount": 11.0,
                    "occurredAt": "2026-01-16T00:00:00Z",
                    "availableAt": "2026-01-16T00:00:00Z",
                    "source": "broker_statement",
                    "sourceRef": "deposit-1",
                },
            },
            {
                "startAt": "2026-01-16T00:00:00Z",
                "endAt": "2026-02-01T00:00:00Z",
                "beginningValue": {
                    "value": 121.0,
                    "observedAt": "2026-01-16T00:00:00Z",
                    "availableAt": "2026-01-16T00:00:00Z",
                    "source": "portfolio_ledger",
                    "sourceRef": "post-flow",
                },
                "endingValueBeforeFlow": {
                    "value": 133.1,
                    "observedAt": "2026-02-01T00:00:00Z",
                    "availableAt": "2026-02-01T00:00:00Z",
                    "source": "portfolio_ledger",
                    "sourceRef": "end",
                },
            },
        ],
    }


def test_portfolio_twr_endpoint_is_non_advisory_and_cash_flow_aware() -> None:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=payload(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["module"] == "portfolio_time_weighted_return"
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert abs(data["timeWeightedReturn"] - 0.21) < 1e-12
    assert data["externalFlowCount"] == 1
    assert data["netExternalFlow"] == 11.0
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["cashInference"] == "forbidden"
    assert len(data["portfolioReturnKey"]) == 64


def test_portfolio_twr_endpoint_fails_closed_on_broken_flow_reconciliation() -> None:
    request = payload()
    request["segments"][1]["beginningValue"]["value"] = 120.0
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "post-flow beginning value" in response.json()["detail"]


def test_portfolio_twr_endpoint_rejects_naive_datetimes() -> None:
    request = payload()
    request["segments"][0]["beginningValue"]["observedAt"] = "2026-01-01T00:00:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _reconciliation_key(
    *,
    portfolio_id: str = "portfolio-1",
    reporting_currency: str = "EUR",
    reconciled: bool = True,
) -> str:
    snapshot_cash = 50.0 if reconciled else 51.0
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-state-reconciliation",
        json={
            "reconstructedState": {
                "portfolioStateKey": "a" * 64,
                "portfolioId": portfolio_id,
                "reportingCurrency": reporting_currency,
                "asOf": "2026-02-02T00:00:00Z",
                "cashBalance": 50.0,
                "positions": [],
            },
            "snapshot": {
                "portfolioId": portfolio_id,
                "reportingCurrency": reporting_currency,
                "cashBalance": snapshot_cash,
                "positions": [],
                "observedAt": "2026-02-02T00:00:00Z",
                "availableAt": "2026-02-02T00:00:00Z",
                "source": "independent_broker_snapshot",
                "sourceRef": f"urn:broker:{portfolio_id}:2026-02-02:{snapshot_cash}",
            },
            "asOf": "2026-02-02T00:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["reconciled"] is reconciled
    assert response.json()["persistence"]["appendOnly"] is True
    return response.json()["data"]["reconciliationKey"]


def payload(*, reconciliation_key: str | None = None) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "EUR",
        "reconciliationKey": reconciliation_key or _reconciliation_key(),
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


def test_portfolio_twr_endpoint_is_non_advisory_cash_flow_aware_and_reconciliation_gated() -> None:
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
    assert data["stateIntegrity"]["reconciled"] is True
    assert data["stateIntegrity"]["tamperVerified"] is True
    assert data["stateIntegrity"]["gate"] == "required_before_measurement"
    assert len(data["stateIntegrity"]["reconciliationKey"]) == 64
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


def test_portfolio_twr_rejects_persisted_but_unreconciled_state() -> None:
    request = payload(reconciliation_key=_reconciliation_key(reconciled=False))
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "reconciled=true" in response.json()["detail"]


def test_portfolio_twr_rejects_reconciliation_from_other_portfolio() -> None:
    request = payload(reconciliation_key=_reconciliation_key(portfolio_id="portfolio-other"))
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "otra cartera" in response.json()["detail"]


def test_persisted_reconciliation_can_be_retrieved_and_tamper_verified() -> None:
    key = _reconciliation_key()
    response = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-state-reconciliation/{key}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["reconciliationKey"] == key
    assert body["data"]["reconciled"] is True
    assert body["persistence"]["appendOnly"] is True
    assert body["persistence"]["tamperVerified"] is True
    assert len(body["persistence"]["artifactHash"]) == 64

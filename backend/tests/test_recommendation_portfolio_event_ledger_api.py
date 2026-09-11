from fastapi.testclient import TestClient

from app.main import app
from app.security.portfolio_owner_storage import owner_scoped_ledger_path


client = TestClient(app)
_TEST_OWNER = 101


def event_payload() -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "eventType": "external_cash_flow",
        "occurredAt": "2026-01-16T00:00:00Z",
        "availableAt": "2026-01-16T00:00:00Z",
        "currency": "EUR",
        "amount": 11.0,
        "instrumentId": None,
        "quantity": None,
        "source": "broker_statement",
        "sourceRef": "deposit-api-1",
        "asOf": "2026-02-02T00:00:00Z",
    }


def test_portfolio_event_ledger_api_persists_and_projects_external_flow(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "portfolio-ledger.jsonl"
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(ledger_path))

    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=event_payload(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["module"] == "portfolio_event_ledger"
    assert data["record"]["sequence"] == 1
    assert len(data["record"]["recordHash"]) == 64
    assert len(data["record"]["event"]["eventKey"]) == 64
    assert data["policy"]["advisoryStatus"] == "no_advice"
    assert data["policy"]["productionEligible"] is False
    assert data["policy"]["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["orderPlacement"] == "forbidden"

    projected = client.get(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/external-cash-flows",
        params={
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "periodStart": "2026-01-01T00:00:00Z",
            "periodEnd": "2026-02-01T00:00:00Z",
            "asOf": "2026-02-02T00:00:00Z",
        },
    )
    assert projected.status_code == 200
    flow_data = projected.json()["data"]
    assert len(flow_data["flows"]) == 1
    assert flow_data["flows"][0]["amount"] == 11.0
    assert flow_data["flows"][0]["sourceRef"] == "deposit-api-1"
    assert owner_scoped_ledger_path(ledger_path, owner_user_id=_TEST_OWNER).exists()
    assert not ledger_path.exists()


def test_portfolio_event_ledger_api_is_idempotent_for_same_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    first = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=event_payload(),
    )
    second = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=event_payload(),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["record"] == second.json()["data"]["record"]


def test_portfolio_event_ledger_api_rejects_order_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    request = event_payload()
    request["eventType"] = "order"
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=request,
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"]


def test_portfolio_event_ledger_api_rejects_naive_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    request = event_payload()
    request["occurredAt"] = "2026-01-16T00:00:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=request,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_portfolio_event_ledger_api_fails_closed_on_unconverted_fx(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    request = event_payload()
    request["currency"] = "USD"
    assert client.post(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/events",
        json=request,
    ).status_code == 200

    response = client.get(
        "/api/v1/recommendations/professional-research/portfolio-event-ledger/external-cash-flows",
        params={
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "periodStart": "2026-01-01T00:00:00Z",
            "periodEnd": "2026-02-01T00:00:00Z",
            "asOf": "2026-02-02T00:00:00Z",
        },
    )
    assert response.status_code == 400
    assert "explicit FX conversion evidence" in response.json()["detail"]

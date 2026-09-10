from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)


client = TestClient(app)
UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW = datetime(2026, 1, 16, tzinfo=UTC)
INTERNAL = datetime(2026, 1, 20, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


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
                "asOf": AS_OF.isoformat(),
                "cashBalance": 50.0,
                "positions": [],
            },
            "snapshot": {
                "portfolioId": portfolio_id,
                "reportingCurrency": reporting_currency,
                "cashBalance": snapshot_cash,
                "positions": [],
                "observedAt": AS_OF.isoformat(),
                "availableAt": AS_OF.isoformat(),
                "source": "independent_broker_snapshot",
                "sourceRef": f"urn:broker:{portfolio_id}:2026-02-02:{snapshot_cash}",
            },
            "asOf": AS_OF.isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["reconciled"] is reconciled
    assert response.json()["persistence"]["appendOnly"] is True
    return response.json()["data"]["reconciliationKey"]


def _append(
    ledger: RecommendationPortfolioEventLedgerService,
    *,
    event_type: str,
    when: datetime,
    amount: float,
    source_ref: str,
    instrument_id: str | None = None,
) -> None:
    ledger.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type=event_type,
            occurred_at=when,
            available_at=when,
            currency="EUR",
            amount=amount,
            instrument_id=instrument_id,
            quantity=None,
            source="broker_statement",
            source_ref=source_ref,
        ),
    )


def _ledger(monkeypatch, tmp_path, *, external_flow: bool = True) -> RecommendationPortfolioEventLedgerService:
    path = tmp_path / "portfolio-event-ledger.jsonl"
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(path))
    ledger = RecommendationPortfolioEventLedgerService(path)
    if external_flow:
        _append(
            ledger,
            event_type="external_cash_flow",
            when=FLOW,
            amount=11.0,
            source_ref="deposit-1",
        )
    _append(
        ledger,
        event_type="cash_dividend",
        when=INTERNAL,
        amount=2.0,
        source_ref="dividend-1",
        instrument_id="instrument-1",
    )
    _append(ledger, event_type="fee", when=INTERNAL, amount=-0.5, source_ref="fee-1")
    _append(ledger, event_type="tax", when=INTERNAL, amount=-0.25, source_ref="tax-1")
    return ledger


def _snapshot(
    when: datetime,
    *,
    value: float,
    phase: str,
    tag: str,
    portfolio_id: str = "portfolio-1",
    currency: str = "EUR",
) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json={
            "portfolioId": portfolio_id,
            "reportingCurrency": currency,
            "value": value,
            "observedAt": when.isoformat(),
            "availableAt": when.isoformat(),
            "phase": phase,
            "source": "broker_net_liquidation_statement",
            "sourceRef": f"twr:{tag}:{when.isoformat()}:{phase}:{value}",
            "asOf": AS_OF.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["snapshotKey"]


def payload(
    *,
    reconciliation_key: str | None = None,
    tag: str = "base",
    post_flow_value: float = 121.0,
) -> dict[str, object]:
    start = _snapshot(START, value=100.0, phase="regular", tag=tag)
    pre = _snapshot(FLOW, value=110.0, phase="pre_external_flow", tag=tag)
    post = _snapshot(FLOW, value=post_flow_value, phase="post_external_flow", tag=tag)
    end = _snapshot(END, value=133.1, phase="regular", tag=tag)
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "EUR",
        "reconciliationKey": reconciliation_key or _reconciliation_key(),
        "asOf": AS_OF.isoformat(),
        "periodStart": START.isoformat(),
        "periodEnd": END.isoformat(),
        "boundaries": [
            {"observedAt": START.isoformat(), "regularSnapshotKey": start},
            {
                "observedAt": FLOW.isoformat(),
                "preFlowSnapshotKey": pre,
                "postFlowSnapshotKey": post,
            },
            {"observedAt": END.isoformat(), "regularSnapshotKey": end},
        ],
    }


def test_portfolio_twr_endpoint_uses_sealed_nlv_and_canonical_server_cash_events(monkeypatch, tmp_path) -> None:
    ledger = _ledger(monkeypatch, tmp_path)
    request = payload(tag="sealed-success")
    expected_snapshot_keys = [
        request["boundaries"][0]["regularSnapshotKey"],
        request["boundaries"][1]["preFlowSnapshotKey"],
        request["boundaries"][1]["postFlowSnapshotKey"],
        request["boundaries"][2]["regularSnapshotKey"],
    ]
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    data = body["data"]
    assert data["module"] == "portfolio_twr_measurement"
    assert data["status"] == "measured_from_canonical_server_side_portfolio_ledger"
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert abs(data["timeWeightedReturn"] - 0.21) < 1e-12
    assert data["externalFlowTotal"] == 11.0
    assert len(data["externalFlowEvents"]) == 1
    assert data["internalCashTotals"] == {
        "cash_dividend": 2.0,
        "fee": -0.5,
        "tax": -0.25,
    }
    assert data["serverSideLedger"]["serverSide"] is True
    assert data["serverSideLedger"]["callerSuppliedEventsAccepted"] is False
    assert data["serverSideLedger"]["ledgerHeadHash"] == ledger.load()[-1].record_hash
    assert data["nlvEvidence"]["callerSuppliedValuesAccepted"] is False
    assert data["nlvEvidence"]["tamperVerified"] is True
    assert data["nlvEvidence"]["snapshotKeys"] == expected_snapshot_keys
    assert data["policy"]["callerSuppliedValuationValues"] is False
    assert data["policy"]["valuationEvidence"] == "persisted_tamper_verified_portfolio_nlv_snapshots"
    assert data["policy"]["callerSuppliedExternalCashFlowLedger"] is False
    assert data["policy"]["callerSuppliedInternalCashEvents"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["stateIntegrity"]["reconciled"] is True
    assert data["stateIntegrity"]["tamperVerified"] is True
    assert data["stateIntegrity"]["gate"] == "required_before_measurement"
    assert len(data["measurementKey"]) == 64
    assert len(data["ledgerMeasurementKey"]) == 64
    assert len(data["coreMeasurementKey"]) == 64
    assert data["measurementKey"] != data["ledgerMeasurementKey"]
    assert body["persistence"]["appendOnly"] is True
    assert body["persistence"]["tamperVerified"] is True

    read = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-time-weighted-return/{data['measurementKey']}"
    )
    assert read.status_code == 200
    assert read.json()["data"] == data
    assert read.json()["persistence"]["tamperVerified"] is True


def test_portfolio_twr_endpoint_rejects_caller_supplied_values_or_cash_events(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(tag="legacy-fields")
    request["boundaries"][0]["preFlowValue"] = 100.0
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 422

    request = payload(tag="legacy-events")
    request["internalCashEvents"] = []
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 422


def test_portfolio_twr_endpoint_fails_closed_on_omitted_ledger_flow(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(tag="omit-flow")
    request["boundaries"] = [request["boundaries"][0], request["boundaries"][2]]
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "missing an exact TWR valuation boundary" in response.json()["detail"]


def test_portfolio_twr_endpoint_rejects_flow_snapshot_pair_without_ledger_flow(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path, external_flow=False)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=payload(tag="invented-flow"),
    )
    assert response.status_code == 400
    assert "non-flow TWR boundary requires regularSnapshotKey only" in response.json()["detail"]


def test_portfolio_twr_endpoint_fails_closed_on_snapshot_pair_vs_flow_mismatch(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=payload(tag="bad-pair", post_flow_value=120.0),
    )
    assert response.status_code == 400
    assert "does not reconcile post_flow_value" in response.json()["detail"]


def test_portfolio_twr_endpoint_rejects_wrong_snapshot_phase(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(tag="wrong-phase")
    wrong = _snapshot(FLOW, value=110.0, phase="regular", tag="wrong-phase-regular")
    request["boundaries"][1]["preFlowSnapshotKey"] = wrong
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "phase does not match" in response.json()["detail"]


def test_portfolio_twr_endpoint_rejects_naive_boundary_datetime(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(tag="naive")
    request["boundaries"][0]["observedAt"] = "2026-01-01T00:00:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_portfolio_twr_rejects_persisted_but_unreconciled_state(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(
        reconciliation_key=_reconciliation_key(reconciled=False),
        tag="unreconciled",
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "reconciled=true" in response.json()["detail"]


def test_portfolio_twr_rejects_reconciliation_from_other_portfolio(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(
        reconciliation_key=_reconciliation_key(portfolio_id="portfolio-other"),
        tag="other-portfolio",
    )
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

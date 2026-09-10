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
SCOPE = "total_net_liquidation_value_in_reporting_currency"


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


def _boundary(when: datetime, *, pre: float, post: float, flow: float, fingerprint: str) -> dict[str, object]:
    return {
        "observedAt": when.isoformat(),
        "availableAt": when.isoformat(),
        "preFlowValue": pre,
        "postFlowValue": post,
        "externalFlowAmount": flow,
        "currency": "EUR",
        "valuationScope": SCOPE,
        "valuationFingerprint": fingerprint,
        "source": "broker_net_liquidation_statement",
        "sourceRef": f"nlv:{when.isoformat()}",
    }


def payload(*, reconciliation_key: str | None = None) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "EUR",
        "reconciliationKey": reconciliation_key or _reconciliation_key(),
        "asOf": AS_OF.isoformat(),
        "periodStart": START.isoformat(),
        "periodEnd": END.isoformat(),
        "boundaries": [
            _boundary(START, pre=100.0, post=100.0, flow=0.0, fingerprint="1" * 64),
            _boundary(FLOW, pre=110.0, post=121.0, flow=11.0, fingerprint="2" * 64),
            _boundary(END, pre=133.1, post=133.1, flow=0.0, fingerprint="3" * 64),
        ],
    }


def test_portfolio_twr_endpoint_uses_only_canonical_server_side_cash_events(monkeypatch, tmp_path) -> None:
    ledger = _ledger(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=payload(),
    )
    assert response.status_code == 200
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
    assert data["serverSideLedger"]["appendOnly"] is True
    assert data["serverSideLedger"]["tamperEvidentHashChain"] is True
    assert data["serverSideLedger"]["ledgerHeadHash"] == ledger.load()[-1].record_hash
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
    assert len(body["persistence"]["artifactHash"]) == 64

    read = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-time-weighted-return/{data['measurementKey']}"
    )
    assert read.status_code == 200
    assert read.json()["data"] == data
    assert read.json()["persistence"]["tamperVerified"] is True


def test_portfolio_twr_endpoint_rejects_caller_supplied_cash_events(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload()
    request["internalCashEvents"] = []
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 422


def test_portfolio_twr_endpoint_fails_closed_on_omitted_or_invented_ledger_flow(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload()
    request["boundaries"] = [request["boundaries"][0], request["boundaries"][2]]
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "missing an exact TWR valuation boundary" in response.json()["detail"]

    _ledger(monkeypatch, tmp_path / "empty", external_flow=False)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=payload(),
    )
    assert response.status_code == 400
    assert "absent from the supplied ledger evidence" in response.json()["detail"]


def test_portfolio_twr_endpoint_fails_closed_on_flow_amount_mismatch(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload()
    request["boundaries"][1]["externalFlowAmount"] = 10.0
    request["boundaries"][1]["postFlowValue"] = 120.0
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "does not match ledger event amount" in response.json()["detail"]


def test_portfolio_twr_endpoint_rejects_naive_datetimes(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload()
    request["boundaries"][0]["observedAt"] = "2026-01-01T00:00:00"
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_portfolio_twr_rejects_persisted_but_unreconciled_state(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
    request = payload(reconciliation_key=_reconciliation_key(reconciled=False))
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request,
    )
    assert response.status_code == 400
    assert "reconciled=true" in response.json()["detail"]


def test_portfolio_twr_rejects_reconciliation_from_other_portfolio(monkeypatch, tmp_path) -> None:
    _ledger(monkeypatch, tmp_path)
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

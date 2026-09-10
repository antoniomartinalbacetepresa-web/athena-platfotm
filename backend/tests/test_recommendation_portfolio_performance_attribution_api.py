from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.api.recommendation_portfolio_performance_attribution as api_module
from app.main import app


client = TestClient(app)
UTC = timezone.utc


def iso(day: int) -> str:
    return datetime(2026, 8, day, 12, tzinfo=UTC).isoformat()


def evidence(value: float, ref: str, *, day: int) -> dict[str, object]:
    return {
        "value": value,
        "availableAt": iso(day),
        "source": "athena-test",
        "sourceRef": ref,
    }


def _reconciliation_key(*, portfolio_id: str = "portfolio-1", reconciled: bool = True) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-state-reconciliation",
        json={
            "reconstructedState": {
                "portfolioStateKey": "d" * 64,
                "portfolioId": portfolio_id,
                "reportingCurrency": "USD",
                "asOf": "2026-09-01T12:00:00Z",
                "cashBalance": 100.0,
                "positions": [],
            },
            "snapshot": {
                "portfolioId": portfolio_id,
                "reportingCurrency": "USD",
                "cashBalance": 100.0 if reconciled else 101.0,
                "positions": [],
                "observedAt": "2026-09-01T12:00:00Z",
                "availableAt": "2026-09-01T12:00:00Z",
                "source": "independent_broker_snapshot",
                "sourceRef": f"urn:broker:attribution:{portfolio_id}:{reconciled}",
            },
            "asOf": "2026-09-01T12:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["reconciled"] is reconciled
    return response.json()["data"]["reconciliationKey"]


def _nlv_snapshot(*, portfolio_id: str, day: int, value: float, tag: str) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json={
            "portfolioId": portfolio_id,
            "reportingCurrency": "USD",
            "value": value,
            "observedAt": iso(day),
            "availableAt": iso(day),
            "phase": "regular",
            "source": "broker_net_liquidation_statement",
            "sourceRef": f"{portfolio_id}:attribution:{tag}:{value}",
            "asOf": "2026-09-01T12:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["persistence"]["tamperVerified"] is True
    return response.json()["data"]["snapshotKey"]


def _measurement_key(monkeypatch, tmp_path, *, portfolio_id: str = "portfolio-1") -> str:
    ledger_path = tmp_path / f"{portfolio_id}-ledger.jsonl"
    monkeypatch.setenv("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", str(ledger_path))
    reconciliation_key = _reconciliation_key(portfolio_id=portfolio_id)
    start_key = _nlv_snapshot(portfolio_id=portfolio_id, day=1, value=100.0, tag="start")
    end_key = _nlv_snapshot(portfolio_id=portfolio_id, day=31, value=103.2, tag="end")
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json={
            "portfolioId": portfolio_id,
            "reportingCurrency": "USD",
            "reconciliationKey": reconciliation_key,
            "asOf": "2026-09-01T12:00:00Z",
            "periodStart": iso(1),
            "periodEnd": iso(31),
            "boundaries": [
                {"observedAt": iso(1), "regularSnapshotKey": start_key},
                {"observedAt": iso(31), "regularSnapshotKey": end_key},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["persistence"]["tamperVerified"] is True
    assert response.json()["data"]["nlvEvidence"]["callerSuppliedValuesAccepted"] is False
    return response.json()["data"]["measurementKey"]


def child(instrument_id: str, symbol: str, total: float, market: float) -> dict[str, object]:
    return {
        "instrumentId": instrument_id,
        "symbol": symbol,
        "instrumentCurrency": "USD",
        "reportingCurrency": "USD",
        "fxPair": "USD/USD",
        "benchmarkId": "SP500_TR",
        "totalReturn": evidence(total, f"{instrument_id}:return", day=31),
        "marketContribution": evidence(market, f"{instrument_id}:market", day=31),
        "fxContribution": evidence(0.0, f"{instrument_id}:fx", day=31),
        "factorContributions": [
            {
                "factor": "quality",
                "contribution": 0.01,
                "availableAt": iso(31),
                "source": "athena-test",
                "sourceRef": f"{instrument_id}:quality",
            }
        ],
    }


def request_body(*, measurement_key: str) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "benchmarkId": "SP500_TR",
        "reportingCurrency": "USD",
        "measurementKey": measurement_key,
        "asOf": datetime(2026, 9, 1, 12, tzinfo=UTC).isoformat(),
        "periodStart": iso(1),
        "periodEnd": iso(31),
        "constituents": [
            {
                "weight": evidence(0.6, "weight:a", day=1),
                "attribution": child("inst-a", "AAA", 0.08, 0.04),
            },
            {
                "weight": evidence(0.4, "weight:b", day=1),
                "attribution": child("inst-b", "BBB", -0.04, -0.01),
            },
        ],
    }


def test_endpoint_reconciles_portfolio_from_sealed_twr_without_enabling_advice_or_weighting(monkeypatch, tmp_path) -> None:
    measurement_key = _measurement_key(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(measurement_key=measurement_key),
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["module"] == "portfolio_performance_attribution"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["weighting"] == "historical_beginning_weights_diagnostic_only"
    assert payload["policy"]["cashFlows"] == "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated"
    assert payload["policy"]["observedReturn"] == "sealed_portfolio_twr_measurement_required"
    assert payload["policy"]["residualInterpretation"] == "unexplained_not_automatic_stock_selection_alpha"
    assert payload["stateIntegrity"]["reconciled"] is True
    assert payload["stateIntegrity"]["tamperVerified"] is True
    assert payload["stateIntegrity"]["gate"] == "required_before_attribution"
    assert payload["performanceMeasurement"]["measurementKey"] == measurement_key
    assert payload["performanceMeasurement"]["tamperVerified"] is True
    assert payload["performanceMeasurement"]["gate"] == "required_before_attribution"
    assert payload["evidence"]["observedPortfolioReturn"]["sourceRef"] == f"twr:{measurement_key}"
    assert abs(payload["observedPortfolioReturn"] - 0.032) < 1e-12
    assert abs(payload["reconstructedPortfolioReturn"] - 0.032) < 1e-12
    assert len(payload["portfolioAttributionKey"]) == 64


def test_endpoint_rejects_lookahead_weight(monkeypatch, tmp_path) -> None:
    body = request_body(measurement_key=_measurement_key(monkeypatch, tmp_path))
    body["constituents"][0]["weight"]["availableAt"] = iso(2)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "not PIT" in response.json()["detail"]


def test_endpoint_rejects_legacy_free_observed_return_and_reconciliation_key(monkeypatch, tmp_path) -> None:
    body = request_body(measurement_key=_measurement_key(monkeypatch, tmp_path))
    body["observedPortfolioReturn"] = evidence(0.032, "caller:return", day=31)
    body["reconciliationKey"] = "a" * 64
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 422


def test_endpoint_rejects_unknown_measurement() -> None:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(measurement_key="9" * 64),
    )
    assert response.status_code == 400
    assert "No persisted portfolio TWR measurement" in response.json()["detail"]


def test_endpoint_rejects_measurement_from_another_portfolio(monkeypatch, tmp_path) -> None:
    other_measurement = _measurement_key(monkeypatch, tmp_path, portfolio_id="portfolio-other")
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(measurement_key=other_measurement),
    )
    assert response.status_code == 400
    assert "another portfolio" in response.json()["detail"]


def test_endpoint_rejects_measurement_from_another_period(monkeypatch, tmp_path) -> None:
    measurement_key = _measurement_key(monkeypatch, tmp_path)
    body = request_body(measurement_key=measurement_key)
    body["periodEnd"] = datetime(2026, 8, 30, 12, tzinfo=UTC).isoformat()
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "period_end" in response.json()["detail"]


def test_api_contract_fails_closed_if_weighting_becomes_ready(monkeypatch, tmp_path) -> None:
    measurement_key = _measurement_key(monkeypatch, tmp_path)
    real_evaluate = api_module.service.evaluate

    class FakeResult:
        def to_api_dict(self) -> dict[str, object]:
            body = request_body(measurement_key=measurement_key)
            request = api_module.PortfolioPerformanceAttributionRequest(**body)
            constituents = []
            for index, item in enumerate(request.constituents):
                child_request = item.attribution
                constituents.append(
                    api_module.PortfolioAttributionConstituent(
                        weight=api_module._evidence(item.weight, f"constituents[{index}].weight"),
                        attribution=api_module.RecommendationPerformanceAttributionInput(
                            instrument_id=child_request.instrumentId,
                            symbol=child_request.symbol,
                            instrument_currency=child_request.instrumentCurrency,
                            reporting_currency=child_request.reportingCurrency,
                            fx_pair=child_request.fxPair,
                            benchmark_id=child_request.benchmarkId,
                            period_start=datetime(2026, 8, 1, 12, tzinfo=UTC),
                            period_end=datetime(2026, 8, 31, 12, tzinfo=UTC),
                            total_return=api_module._evidence(child_request.totalReturn, "total"),
                            market_contribution=api_module._evidence(child_request.marketContribution, "market"),
                            fx_contribution=api_module._evidence(child_request.fxContribution, "fx"),
                            factor_contributions=tuple(
                                api_module.FactorContributionEvidence(
                                    factor=factor.factor,
                                    contribution=factor.contribution,
                                    available_at=factor.availableAt,
                                    source=factor.source,
                                    source_ref=factor.sourceRef,
                                )
                                for factor in child_request.factorContributions
                            ),
                        ),
                    )
                )
            payload = real_evaluate(
                as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
                item=api_module.RecommendationPortfolioPerformanceAttributionInput(
                    portfolio_id=request.portfolioId,
                    benchmark_id=request.benchmarkId,
                    reporting_currency=request.reportingCurrency,
                    period_start=datetime(2026, 8, 1, 12, tzinfo=UTC),
                    period_end=datetime(2026, 8, 31, 12, tzinfo=UTC),
                    observed_portfolio_return=api_module.AttributionEvidence(
                        value=0.032,
                        available_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
                        source="athena_persisted_portfolio_twr",
                        source_ref=f"twr:{measurement_key}",
                    ),
                    constituents=tuple(constituents),
                ),
            ).to_api_dict()
            payload["isWeightingReady"] = True
            return payload

    monkeypatch.setattr(api_module.service, "evaluate", lambda **kwargs: FakeResult())
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(measurement_key=measurement_key),
    )
    assert response.status_code == 500
    assert "weighting" in response.json()["detail"].lower()

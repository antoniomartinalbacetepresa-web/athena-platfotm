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


def request_body() -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "benchmarkId": "SP500_TR",
        "reportingCurrency": "USD",
        "asOf": datetime(2026, 9, 1, 12, tzinfo=UTC).isoformat(),
        "periodStart": iso(1),
        "periodEnd": iso(31),
        "observedPortfolioReturn": evidence(0.032, "portfolio:return", day=31),
        "constituents": [
            {
                "weight": evidence(0.6, "weight:a", day=1),
                "attribution": child("inst-a", "AAA", 0.08, 0.04),
            },
            {
                "weight": evidence(0.4, "weight:b", day=1),
                "attribution": child("inst-b", "BBB", -0.02, -0.01),
            },
        ],
    }


def test_endpoint_reconciles_portfolio_without_enabling_advice_or_weighting() -> None:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["module"] == "portfolio_performance_attribution"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["weighting"] == "historical_beginning_weights_diagnostic_only"
    assert payload["policy"]["cashFlows"] == "unsupported_fail_closed"
    assert payload["policy"]["residualInterpretation"] == "unexplained_not_automatic_stock_selection_alpha"
    assert abs(payload["reconstructedPortfolioReturn"] - 0.032) < 1e-12
    assert len(payload["portfolioAttributionKey"]) == 64


def test_endpoint_rejects_lookahead_weight() -> None:
    body = request_body()
    body["constituents"][0]["weight"]["availableAt"] = iso(2)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "not PIT" in response.json()["detail"]


def test_endpoint_rejects_non_reconciling_return() -> None:
    body = request_body()
    body["observedPortfolioReturn"]["value"] = 0.05
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "does not reconcile" in response.json()["detail"]


def test_api_contract_fails_closed_if_weighting_becomes_ready(monkeypatch) -> None:
    real_evaluate = api_module.service.evaluate

    class FakeResult:
        def to_api_dict(self) -> dict[str, object]:
            body = request_body()
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
                    observed_portfolio_return=api_module._evidence(request.observedPortfolioReturn, "observed"),
                    constituents=tuple(constituents),
                ),
            ).to_api_dict()
            payload["isWeightingReady"] = True
            return payload

    monkeypatch.setattr(api_module.service, "evaluate", lambda **kwargs: FakeResult())
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(),
    )
    assert response.status_code == 500
    assert "weighting" in response.json()["detail"].lower()

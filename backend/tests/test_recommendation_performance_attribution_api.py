from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.api.recommendation_performance_attribution as api_module
from app.main import app


client = TestClient(app)
UTC = timezone.utc


def iso(day: int) -> str:
    return datetime(2026, 1, day, 12, tzinfo=UTC).isoformat()


def request_body() -> dict[str, object]:
    return {
        "instrumentId": "issuer:US:0378331005",
        "symbol": "AAPL",
        "instrumentCurrency": "USD",
        "reportingCurrency": "EUR",
        "fxPair": "USD/EUR",
        "benchmarkId": "benchmark:MSCI_WORLD",
        "asOf": iso(11),
        "periodStart": iso(1),
        "periodEnd": iso(9),
        "totalReturn": {
            "value": 0.12,
            "availableAt": iso(10),
            "source": "portfolio-ledger",
            "sourceRef": "return-1",
        },
        "marketContribution": {
            "value": 0.05,
            "availableAt": iso(10),
            "source": "factor-model",
            "sourceRef": "market-1",
        },
        "fxContribution": {
            "value": 0.01,
            "availableAt": iso(10),
            "source": "fx-model",
            "sourceRef": "fx-1",
        },
        "factorContributions": [
            {
                "factor": "momentum",
                "contribution": 0.02,
                "availableAt": iso(10),
                "source": "factor-model",
                "sourceRef": "momentum-1",
            }
        ],
    }


def test_endpoint_returns_research_only_attribution_with_bound_fx_identity() -> None:
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=request_body(),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["module"] == "performance_attribution"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["causalClaim"] == "forbidden_arithmetic_attribution_only"
    assert payload["policy"]["fx"] == "explicit_currency_pair_bound_fail_closed"
    assert payload["benchmarkId"] == "benchmark:MSCI_WORLD"
    assert payload["currency"] == {
        "instrumentCurrency": "USD",
        "reportingCurrency": "EUR",
        "fxPair": "USD/EUR",
        "conversionRequired": True,
    }
    assert len(payload["attributionKey"]) == 64
    assert abs(payload["explainedReturn"] - 0.08) < 1e-12
    assert abs(payload["residualReturn"] - 0.04) < 1e-12


def test_endpoint_rejects_timezone_naive_as_of_before_service_call(monkeypatch) -> None:
    body = request_body()
    body["asOf"] = "2026-01-11T12:00:00"
    called = False

    def fail_if_called(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("service should not be called")

    monkeypatch.setattr(api_module.service, "evaluate", fail_if_called)
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert called is False


def test_endpoint_rejects_lookahead_factor_evidence() -> None:
    body = request_body()
    body["factorContributions"][0]["availableAt"] = iso(12)
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "not PIT" in response.json()["detail"]


def test_endpoint_rejects_inconsistent_fx_pair() -> None:
    body = request_body()
    body["fxPair"] = "EUR/USD"
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "fx_pair" in response.json()["detail"]


def test_endpoint_rejects_non_zero_fx_for_same_currency() -> None:
    body = request_body()
    body["reportingCurrency"] = "USD"
    body["fxPair"] = "USD/USD"
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "must be zero" in response.json()["detail"]


def test_api_contract_fails_closed_on_alpha_claim(monkeypatch) -> None:
    class FakeResult:
        def to_api_dict(self) -> dict[str, object]:
            return {
                "module": "performance_attribution",
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
                "attributionKey": "a" * 64,
                "instrumentId": "issuer:US:0378331005",
                "symbol": "AAPL",
                "benchmarkId": "benchmark:MSCI_WORLD",
                "currency": {
                    "instrumentCurrency": "USD",
                    "reportingCurrency": "EUR",
                    "fxPair": "USD/EUR",
                    "conversionRequired": True,
                },
                "asOf": iso(11),
                "periodStart": iso(1),
                "periodEnd": iso(9),
                "totalReturn": 0.12,
                "marketContribution": 0.05,
                "fxContribution": 0.01,
                "factorContributions": {"momentum": 0.02},
                "explainedReturn": 0.08,
                "residualReturn": 0.04,
                "evidence": {
                    "totalReturn": {},
                    "marketContribution": {},
                    "fxContribution": {},
                    "factorContributions": {},
                },
                "policy": {
                    "automaticTrading": False,
                    "automaticProductionPromotion": False,
                    "causalClaim": "residual_is_stock_selection_alpha",
                    "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                    "fx": "explicit_currency_pair_bound_fail_closed",
                    "identity": "deterministic_sha256_attribution_key",
                    "benchmark": "explicit_market_contribution_identity",
                },
            }

    monkeypatch.setattr(api_module.service, "evaluate", lambda **kwargs: FakeResult())
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=request_body(),
    )
    assert response.status_code == 500
    assert "causal" in response.json()["detail"].lower()


def test_api_contract_fails_closed_on_invalid_attribution_key(monkeypatch) -> None:
    real_result = api_module.service.evaluate

    class FakeResult:
        def to_api_dict(self) -> dict[str, object]:
            payload = real_result(
                as_of=datetime(2026, 1, 11, 12, tzinfo=UTC),
                item=api_module.RecommendationPerformanceAttributionInput(
                    instrument_id="issuer:US:0378331005",
                    symbol="AAPL",
                    instrument_currency="USD",
                    reporting_currency="EUR",
                    fx_pair="USD/EUR",
                    benchmark_id="benchmark:MSCI_WORLD",
                    period_start=datetime(2026, 1, 1, 12, tzinfo=UTC),
                    period_end=datetime(2026, 1, 9, 12, tzinfo=UTC),
                    total_return=api_module.AttributionEvidence(0.12, datetime(2026, 1, 10, 12, tzinfo=UTC), "ledger", "return"),
                    market_contribution=api_module.AttributionEvidence(0.05, datetime(2026, 1, 10, 12, tzinfo=UTC), "model", "market"),
                    fx_contribution=api_module.AttributionEvidence(0.01, datetime(2026, 1, 10, 12, tzinfo=UTC), "fx", "fx"),
                    factor_contributions=(),
                ),
            ).to_api_dict()
            payload["attributionKey"] = "not-a-sha"
            return payload

    monkeypatch.setattr(api_module.service, "evaluate", lambda **kwargs: FakeResult())
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=request_body(),
    )
    assert response.status_code == 500
    assert "attributionkey" in response.json()["detail"].lower()

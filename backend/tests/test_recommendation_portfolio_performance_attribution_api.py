from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.api.recommendation_portfolio_performance_attribution as api_module
from app.main import app
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


client = TestClient(app)
UTC = timezone.utc


def iso(day: int) -> str:
    return datetime(2026, 8, day, 12, tzinfo=UTC).isoformat()


def as_of_iso() -> str:
    return datetime(2026, 9, 1, 12, tzinfo=UTC).isoformat()


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
                "asOf": as_of_iso(),
                "cashBalance": 100.0,
                "positions": [],
            },
            "snapshot": {
                "portfolioId": portfolio_id,
                "reportingCurrency": "USD",
                "cashBalance": 100.0 if reconciled else 101.0,
                "positions": [],
                "observedAt": as_of_iso(),
                "availableAt": as_of_iso(),
                "source": "independent_broker_snapshot",
                "sourceRef": f"urn:broker:attribution:{portfolio_id}:{reconciled}",
            },
            "asOf": as_of_iso(),
        },
    )
    assert response.status_code == 200, response.text
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
            "asOf": as_of_iso(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["persistence"]["tamperVerified"] is True
    return response.json()["data"]["snapshotKey"]


def _measurement_key(monkeypatch, tmp_path, *, portfolio_id: str = "portfolio-1") -> str:
    monkeypatch.setenv(
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH",
        str(tmp_path / f"{portfolio_id}-ledger.jsonl"),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json={
            "portfolioId": portfolio_id,
            "reportingCurrency": "USD",
            "reconciliationKey": _reconciliation_key(portfolio_id=portfolio_id),
            "asOf": as_of_iso(),
            "periodStart": iso(1),
            "periodEnd": iso(31),
            "boundaries": [
                {
                    "observedAt": iso(1),
                    "regularSnapshotKey": _nlv_snapshot(
                        portfolio_id=portfolio_id, day=1, value=100.0, tag="start"
                    ),
                },
                {
                    "observedAt": iso(31),
                    "regularSnapshotKey": _nlv_snapshot(
                        portfolio_id=portfolio_id, day=31, value=103.2, tag="end"
                    ),
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["persistence"]["tamperVerified"] is True
    return response.json()["data"]["measurementKey"]


def _weight_evidence_key(*, portfolio_id: str = "portfolio-1", cash_weight: float = 0.0) -> str:
    service = RecommendationReconciledPortfolioWeightService()
    if cash_weight == 0.0:
        first_quantity, first_value, first_weight = 6.0, 60.0, 0.6
        second_quantity, second_value, second_weight = 4.0, 40.0, 0.4
        cash_balance, invested_value = 0.0, 100.0
    else:
        first_quantity, first_value, first_weight = 5.0, 50.0, 0.5
        second_quantity, second_value, second_weight = 4.0, 40.0, 0.4
        cash_balance, invested_value = 10.0, 90.0
    positions = [
        {
            "instrumentId": 101,
            "symbol": "AAA",
            "quantity": first_quantity,
            "positionValueInReportingCurrency": first_value,
            "canonicalIdentity": {"instrumentId": 101},
            "price": 10.0,
            "priceSourceProvider": "official_market_source",
            "priceObservedAt": iso(1),
            "priceRetrievedAt": iso(1),
            "fx": {"rate": 1.0, "historicalPointInTimeEligible": True},
            "weight": first_weight,
        },
        {
            "instrumentId": 202,
            "symbol": "BBB",
            "quantity": second_quantity,
            "positionValueInReportingCurrency": second_value,
            "canonicalIdentity": {"instrumentId": 202},
            "price": 10.0,
            "priceSourceProvider": "official_market_source",
            "priceObservedAt": iso(1),
            "priceRetrievedAt": iso(1),
            "fx": {"rate": 1.0, "historicalPointInTimeEligible": True},
            "weight": second_weight,
        },
    ]
    core = {
        "artifactVersion": service.ARTIFACT_VERSION,
        "portfolioId": portfolio_id,
        "asOf": iso(1),
        "reportingCurrency": "USD",
        "reconciliationKey": "1" * 64,
        "portfolioStateKey": "2" * 64,
        "portfolioValuationEvidenceFingerprint": "3" * 64,
        "cashBalance": cash_balance,
        "cashWeight": cash_weight,
        "investedPositionsValue": invested_value,
        "totalPortfolioValue": 100.0,
        "positions": positions,
        "snapshotProvenance": {
            "observedAt": iso(1),
            "availableAt": iso(1),
            "source": "independent_broker_snapshot",
            "sourceRef": f"urn:test:attribution:weights:{portfolio_id}:{cash_weight}",
        },
    }
    artifact = {
        "module": "reconciled_portfolio_weights",
        "status": "diagnostic_weights_derived_from_reconciled_state_and_pit_valuation",
        **core,
        "weightEvidenceKey": service._fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "allocationEligible": False,
        "automaticTrading": False,
        "policy": {
            "weightDerivation": "reconciled_quantities_plus_sealed_pit_valuation_plus_explicit_cash",
            "cash": "from_independent_reconciled_snapshot_never_inferred",
            "prices": "from_sealed_pit_valuation",
            "fx": "from_sealed_pit_valuation_never_implicitly_converted",
            "positionIdentity": "exact_instrument_set_and_quantity_match_required",
            "missingEvidence": "fail_closed",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "allocationAuthority": "not_granted_diagnostic_weights_only",
        },
    }
    return str(api_module._weight_repository.append(artifact=artifact)["artifact"]["weightEvidenceKey"])


def child_payload(
    instrument_id: str,
    symbol: str,
    total: float,
    market: float,
    *,
    benchmark_id: str = "SP500_TR",
    period_end: int = 31,
) -> dict[str, object]:
    return {
        "instrumentId": instrument_id,
        "symbol": symbol,
        "instrumentCurrency": "USD",
        "reportingCurrency": "USD",
        "fxPair": "USD/USD",
        "benchmarkId": benchmark_id,
        "asOf": as_of_iso(),
        "periodStart": iso(1),
        "periodEnd": iso(period_end),
        "totalReturn": evidence(total, f"{instrument_id}:return:{benchmark_id}:{period_end}", day=period_end),
        "marketContribution": evidence(market, f"{instrument_id}:market:{benchmark_id}:{period_end}", day=period_end),
        "fxContribution": evidence(0.0, f"{instrument_id}:fx:{period_end}", day=period_end),
        "factorContributions": [
            {
                "factor": "quality",
                "contribution": 0.01,
                "availableAt": iso(period_end),
                "source": "athena-test",
                "sourceRef": f"{instrument_id}:quality:{period_end}",
            }
        ],
    }


def _child_key(
    instrument_id: str,
    symbol: str,
    total: float,
    market: float,
    *,
    benchmark_id: str = "SP500_TR",
    period_end: int = 31,
) -> str:
    response = client.post(
        "/api/v1/recommendations/professional-research/performance-attribution",
        json=child_payload(
            instrument_id,
            symbol,
            total,
            market,
            benchmark_id=benchmark_id,
            period_end=period_end,
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["persistence"]["tamperVerified"] is True
    return response.json()["data"]["attributionKey"]


def request_body(*, measurement_key: str, weight_evidence_key: str) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "benchmarkId": "SP500_TR",
        "reportingCurrency": "USD",
        "measurementKey": measurement_key,
        "weightEvidenceKey": weight_evidence_key,
        "asOf": as_of_iso(),
        "periodStart": iso(1),
        "periodEnd": iso(31),
        "constituents": [
            {"attributionKey": _child_key("101", "AAA", 0.08, 0.04)},
            {"attributionKey": _child_key("202", "BBB", -0.04, -0.01)},
        ],
    }


def _valid_body(monkeypatch, tmp_path) -> dict[str, object]:
    return request_body(
        measurement_key=_measurement_key(monkeypatch, tmp_path),
        weight_evidence_key=_weight_evidence_key(),
    )


def test_endpoint_reconciles_from_sealed_twr_weights_and_child_attributions(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["module"] == "portfolio_performance_attribution"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["weightEvidence"] == "persisted_tamper_verified_reconciled_beginning_weights_required"
    assert payload["policy"]["childAttributionEvidence"] == "persisted_tamper_verified_content_bound_attribution_keys_required"
    assert payload["policy"]["cashAttribution"] == "nonzero_beginning_cash_blocked_until_explicit_cash_attribution"
    assert payload["childAttributionEvidence"]["callerSuppliedChildAttributionsAccepted"] is False
    assert payload["childAttributionEvidence"]["tamperVerified"] is True
    assert payload["childAttributionEvidence"]["attributionKeys"] == [
        item["attributionKey"] for item in body["constituents"]
    ]
    assert payload["weightEvidence"]["weightEvidenceKey"] == body["weightEvidenceKey"]
    assert payload["performanceMeasurement"]["measurementKey"] == body["measurementKey"]
    assert payload["stateIntegrity"]["reconciled"] is True
    assert abs(payload["observedPortfolioReturn"] - 0.032) < 1e-12
    assert abs(payload["reconstructedPortfolioReturn"] - 0.032) < 1e-12
    assert len(payload["portfolioAttributionKey"]) == 64


def test_endpoint_rejects_legacy_raw_child_payload(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    body["constituents"][0]["attribution"] = child_payload("101", "AAA", 0.08, 0.04)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 422


def test_endpoint_rejects_unknown_child_attribution_key(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    body["constituents"][0]["attributionKey"] = "9" * 64
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "No existe Performance Attribution" in response.json()["detail"]


def test_endpoint_rejects_child_from_another_benchmark(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    body["constituents"][0]["attributionKey"] = _child_key(
        "101", "AAA", 0.08, 0.04, benchmark_id="OTHER_BENCHMARK"
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "benchmark" in response.json()["detail"].lower()


def test_endpoint_rejects_child_from_another_period(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    body["constituents"][0]["attributionKey"] = _child_key(
        "101", "AAA", 0.08, 0.04, period_end=30
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "periodEnd" in response.json()["detail"]


def test_endpoint_blocks_nonzero_beginning_cash_until_cash_attribution_exists(monkeypatch, tmp_path) -> None:
    body = request_body(
        measurement_key=_measurement_key(monkeypatch, tmp_path),
        weight_evidence_key=_weight_evidence_key(cash_weight=0.1),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "cash inicial" in response.json()["detail"]


def test_endpoint_rejects_legacy_free_observed_return_and_reconciliation_key(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
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
        json=request_body(measurement_key="9" * 64, weight_evidence_key="8" * 64),
    )
    assert response.status_code == 400
    assert "No persisted portfolio TWR measurement" in response.json()["detail"]


def test_endpoint_rejects_measurement_from_another_portfolio(monkeypatch, tmp_path) -> None:
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=request_body(
            measurement_key=_measurement_key(monkeypatch, tmp_path, portfolio_id="portfolio-other"),
            weight_evidence_key=_weight_evidence_key(),
        ),
    )
    assert response.status_code == 400
    assert "another portfolio" in response.json()["detail"]


def test_endpoint_rejects_weight_evidence_from_another_portfolio(monkeypatch, tmp_path) -> None:
    body = request_body(
        measurement_key=_measurement_key(monkeypatch, tmp_path),
        weight_evidence_key=_weight_evidence_key(portfolio_id="portfolio-other"),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "otra cartera" in response.json()["detail"]


def test_endpoint_rejects_child_instrument_set_not_equal_to_weight_evidence(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    body["constituents"].pop()
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 400
    assert "exactamente los instrumentos" in response.json()["detail"]


def test_api_contract_fails_closed_if_weighting_becomes_ready(monkeypatch, tmp_path) -> None:
    body = _valid_body(monkeypatch, tmp_path)
    real_evaluate = api_module.service.evaluate

    class FakeResult:
        def __init__(self, real_result) -> None:
            self._real_result = real_result

        def to_api_dict(self) -> dict[str, object]:
            payload = self._real_result.to_api_dict()
            payload["isWeightingReady"] = True
            return payload

    def fake_evaluate(**kwargs):
        return FakeResult(real_evaluate(**kwargs))

    monkeypatch.setattr(api_module.service, "evaluate", fake_evaluate)
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json=body,
    )
    assert response.status_code == 500
    assert "weighting" in response.json()["detail"].lower()

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk as factor_risk_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"
MARKET_KEY = "a" * 64


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


class _ReconciliationRepository:
    def __init__(self, error: ValueError | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def require_reconciled(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"portfolio_state_key": "e" * 64, "artifact": {"reconciled": True}}


class _ValuationRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"artifact": {"portfolioValuationEvidenceFingerprint": "c" * 64}}

    def validate_record(self, record: dict[str, object]) -> dict[str, object]:
        return record


class _WeightService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "portfolioId": "portfolio-1",
            "reportingCurrency": "USD",
            "asOf": AS_OF,
            "reconciliationKey": "f" * 64,
            "portfolioStateKey": "e" * 64,
            "portfolioValuationEvidenceFingerprint": "c" * 64,
            "weightEvidenceKey": "d" * 64,
            "cashWeight": 0.0,
            "positions": [{"instrumentId": 1, "symbol": "AAA", "weight": 1.0}],
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


class _FactorExposureRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "artifact": {
                "factorExposureKey": MARKET_KEY,
                "instrumentId": 1,
                "benchmarkInstrumentId": 99,
                "asOf": AS_OF,
                "availableAt": AVAILABLE_AT,
                "factors": {"market": 1.0},
            }
        }


def _position_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrumentId": 1,
        "symbol": "AAA",
        "weight": 1.0,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "sealed_market_beta+pit_factor_store",
        "sourceRef": f"market:{MARKET_KEY};caller:factor:1:2025-12-31",
        "factors": {"market": 1.0, "usd_fx": 0.2},
    }
    payload.update(overrides)
    return payload


def _policy(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "temporal": "all_factor_exposures_available_at_must_be_lte_as_of",
        "identity": "duplicate_instrument_or_symbol_forbidden",
        "finiteData": "all_weights_and_exposures_must_be_finite",
        "provenance": "every_position_requires_source_and_source_ref_and_is_returned_for_audit",
        "missingFactorCoverage": "reported_explicitly_never_imputed_as_zero",
        "fx": "usd_fx_is_explicit_factor_not_silently_netting_currency_risk",
        "dominantFactor": "only_selected_from_factors_covering_all_invested_weight",
        "thresholds": "not_calibrated",
        "interpretation": "portfolio_factor_diagnostic_not_position_sizing_or_trade_advice",
        "automaticTrading": False,
        "automaticProductionPromotion": False,
    }
    payload.update(overrides)
    return payload


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "asOf": AS_OF,
        "positionCount": 1,
        "investedWeight": 1.0,
        "cashWeight": 0.0,
        "positions": [_position_payload()],
        "weightedExposures": {
            "low_volatility": 0.0,
            "market": 1.0,
            "momentum": 0.0,
            "quality": 0.0,
            "rates": 0.0,
            "size": 0.0,
            "usd_fx": 0.2,
            "value": 0.0,
        },
        "factorCoverageWeights": {
            "low_volatility": 0.0,
            "market": 1.0,
            "momentum": 0.0,
            "quality": 0.0,
            "rates": 0.0,
            "size": 0.0,
            "usd_fx": 1.0,
            "value": 0.0,
        },
        "fullyCoveredFactors": ["market", "usd_fx"],
        "grossFactorExposure": 1.2,
        "maxAbsoluteFactorExposure": 1.0,
        "dominantFactor": "market",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": _policy(),
    }
    payload.update(overrides)
    return payload


def _request() -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "f" * 64,
        "portfolioValuationEvidenceFingerprint": "c" * 64,
        "asOf": AS_OF,
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "marketExposureKey": MARKET_KEY,
                "exposureAvailableAt": AVAILABLE_AT,
                "source": "pit_factor_store",
                "sourceRef": "factor:1:2025-12-31",
                "factors": {"usd_fx": 0.2},
            }
        ],
    }


def _install_evidence(monkeypatch, *, reconciliation_error: ValueError | None = None):
    reconciliation = _ReconciliationRepository(reconciliation_error)
    valuation = _ValuationRepository()
    weights = _WeightService()
    factors = _FactorExposureRepository()
    monkeypatch.setattr(factor_risk_api, "_reconciliation_repository", reconciliation)
    monkeypatch.setattr(factor_risk_api, "_valuation_repository", valuation)
    monkeypatch.setattr(factor_risk_api, "_weight_service", weights)
    monkeypatch.setattr(factor_risk_api, "_factor_exposure_repository", factors)
    return reconciliation, valuation, weights, factors


def test_factor_risk_endpoint_uses_sealed_market_and_reconciled_weights(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    reconciliation, valuation, weights, factors = _install_evidence(monkeypatch)
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=_request())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["stateIntegrity"]["reconciled"] is True
    assert data["stateIntegrity"]["marketFactorDerivation"] == "sealed_pit_market_observations_only"
    assert data["stateIntegrity"]["callerSuppliedMarketAccepted"] is False
    assert data["stateIntegrity"]["marketExposureKeys"]["1"] == MARKET_KEY
    evaluated = service.calls[0]["positions"][0]  # type: ignore[index]
    assert evaluated.weight == 1.0
    assert evaluated.factors["market"] == 1.0
    assert evaluated.factors["usd_fx"] == 0.2
    assert len(reconciliation.calls) == len(valuation.calls) == len(weights.calls) == len(factors.calls) == 1


def test_factor_risk_api_rejects_caller_supplied_weight(monkeypatch) -> None:
    _install_evidence(monkeypatch)
    body = _request()
    body["positions"][0]["weight"] = 0.99  # type: ignore[index]
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=body)
    assert response.status_code == 422


def test_factor_risk_api_rejects_caller_supplied_market(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["positions"][0]["factors"]["market"] = 9.0  # type: ignore[index]
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=body)
    assert response.status_code == 400
    assert "no puede suministrar factor market" in response.json()["detail"]
    assert service.calls == []


def test_factor_risk_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    _install_evidence(monkeypatch)
    unsafe_payloads = (
        _payload(advisoryStatus="buy"),
        _payload(productionEligible=True),
        _payload(isWeightingReady=True),
        _payload(policy=_policy(automaticTrading=True)),
        _payload(policy=_policy(automaticProductionPromotion=True)),
        _payload(policy=_policy(missingFactorCoverage="imputed_zero")),
        _payload(policy=_policy(thresholds="calibrated")),
        _payload(investedWeight=float("nan")),
        _payload(cashWeight=0.2),
        _payload(weightedExposures={"market": float("inf")}),
        _payload(factorCoverageWeights={"market": 2.0}),
        _payload(fullyCoveredFactors=["unknown"]),
        _payload(positions=[_position_payload(sourceRef="")]),
        _payload(dominantFactor="quality"),
    )
    for payload in unsafe_payloads:
        monkeypatch.setattr(factor_risk_api, "factor_risk_service", _Service(payload))
        response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=_request())
        assert response.status_code == 500


def test_factor_risk_api_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    reconciliation, valuation, weights, factors = _install_evidence(monkeypatch)
    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=body)
    assert response.status_code == 400
    assert service.calls == []
    assert reconciliation.calls == valuation.calls == weights.calls == factors.calls == []


def test_factor_risk_api_blocks_before_service_when_reconciliation_fails(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    reconciliation, valuation, weights, factors = _install_evidence(
        monkeypatch,
        reconciliation_error=ValueError("La reconciliación persistida no está reconciled=true; downstream bloqueado."),
    )
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=_request())
    assert response.status_code == 400
    assert "reconciled=true" in response.json()["detail"]
    assert service.calls == []
    assert len(reconciliation.calls) == 1
    assert valuation.calls == weights.calls == factors.calls == []


def test_factor_risk_api_rejects_factor_identity_not_in_weight_evidence(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["positions"][0]["instrumentId"] = 2  # type: ignore[index]
    response = client.post("/api/v1/recommendations/professional-research/factor-risk", json=body)
    assert response.status_code == 400
    assert "identity mismatch" in response.json()["detail"]
    assert service.calls == []

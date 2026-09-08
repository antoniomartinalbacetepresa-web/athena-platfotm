from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk as factor_risk_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"


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
        return {
            "portfolio_state_key": "e" * 64,
            "artifact": {"reconciled": True},
        }


def _position_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrumentId": 1,
        "symbol": "AAA",
        "weight": 1.0,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:1:2025-12-31",
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
        "asOf": AS_OF,
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "weight": 1.0,
                "exposureAvailableAt": AVAILABLE_AT,
                "source": "pit_factor_store",
                "sourceRef": "factor:1:2025-12-31",
                "factors": {"market": 1.0, "usd_fx": 0.2},
            }
        ],
    }


def _install_gate(monkeypatch, *, error: ValueError | None = None) -> _ReconciliationRepository:
    repository = _ReconciliationRepository(error)
    monkeypatch.setattr(factor_risk_api, "_reconciliation_repository", repository)
    return repository


def test_factor_risk_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    repository = _install_gate(monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_request(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["portfolioId"] == "portfolio-1"
    assert data["reportingCurrency"] == "USD"
    assert data["stateIntegrity"]["reconciled"] is True
    assert data["stateIntegrity"]["tamperVerified"] is True
    assert data["stateIntegrity"]["gate"] == "required_before_factor_risk"
    assert data["stateIntegrity"]["weightDerivation"] == "not_yet_derived_from_reconciled_state"
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["automaticProductionPromotion"] is False
    assert data["policy"]["thresholds"] == "not_calibrated"
    assert data["positions"][0]["sourceRef"] == "factor:1:2025-12-31"
    assert data["factorCoverageWeights"]["usd_fx"] == 1.0
    assert len(service.calls) == 1
    assert len(repository.calls) == 1


def test_factor_risk_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    _install_gate(monkeypatch)
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
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-risk",
            json=_request(),
        )
        assert response.status_code == 500


def test_factor_risk_api_rejects_duplicate_output_identity(monkeypatch) -> None:
    service = _Service(
        _payload(
            positionCount=2,
            positions=[
                _position_payload(),
                _position_payload(symbol="BBB"),
            ],
        )
    )
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    _install_gate(monkeypatch)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_request(),
    )

    assert response.status_code == 500


def test_factor_risk_api_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    repository = _install_gate(monkeypatch)
    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []
    assert repository.calls == []


def test_factor_risk_api_rejects_naive_exposure_timestamp_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    _install_gate(monkeypatch)
    body = _request()
    body["positions"][0]["exposureAvailableAt"] = "2025-12-31T23:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_factor_risk_api_blocks_before_service_when_reconciliation_fails(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(factor_risk_api, "factor_risk_service", service)
    repository = _install_gate(
        monkeypatch,
        error=ValueError("La reconciliación persistida no está reconciled=true; downstream bloqueado."),
    )

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_request(),
    )

    assert response.status_code == 400
    assert "reconciled=true" in response.json()["detail"]
    assert service.calls == []
    assert len(repository.calls) == 1

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk as api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"
MARKET_KEY = "a" * 64
RATE_KEY = "b" * 64


@dataclass(frozen=True)
class _Result:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Service:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> _Result:
        self.calls.append(kwargs)
        positions = kwargs["positions"]
        position = positions[0]  # type: ignore[index]
        factors = dict(position.factors)
        exposures = {name: float(value) for name, value in factors.items()}
        coverage = {name: 1.0 for name in factors}
        return _Result(
            {
                "status": "diagnostic_ready",
                "asOf": AS_OF,
                "positionCount": 1,
                "investedWeight": 1.0,
                "cashWeight": 0.0,
                "positions": [
                    {
                        "instrumentId": 1,
                        "symbol": "AAA",
                        "weight": 1.0,
                        "exposureAvailableAt": position.exposure_available_at.isoformat(),
                        "source": position.source,
                        "sourceRef": position.source_ref,
                        "factors": factors,
                    }
                ],
                "weightedExposures": exposures,
                "factorCoverageWeights": coverage,
                "fullyCoveredFactors": sorted(factors),
                "grossFactorExposure": sum(abs(value) for value in exposures.values()),
                "maxAbsoluteFactorExposure": max(abs(value) for value in exposures.values()),
                "dominantFactor": max(exposures, key=lambda name: abs(exposures[name])),
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
                "policy": {
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
                },
            }
        )


class _Reconciliation:
    def require_reconciled(self, **_: object) -> dict[str, object]:
        return {"portfolio_state_key": "e" * 64, "artifact": {"reconciled": True}}


class _Valuation:
    def get(self, **_: object) -> dict[str, object]:
        return {
            "artifact": {
                "portfolioValuationEvidenceFingerprint": "c" * 64,
                "positions": [
                    {
                        "instrumentId": 1,
                        "instrumentCurrency": "USD",
                        "fx": {
                            "rate": 1.0,
                            "observedAt": AVAILABLE_AT,
                            "retrievedAt": AVAILABLE_AT,
                            "historicalPointInTimeEligible": True,
                        },
                    }
                ],
            }
        }

    def validate_record(self, record: dict[str, object]) -> dict[str, object]:
        return record


class _Weights:
    def build(self, **_: object) -> dict[str, object]:
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


class _Market:
    def get(self, **_: object) -> dict[str, object]:
        return {
            "artifact": {
                "factorExposureKey": MARKET_KEY,
                "instrumentId": 1,
                "asOf": AS_OF,
                "availableAt": AVAILABLE_AT,
                "factors": {"market": 1.0},
            }
        }


class _Rates:
    def __init__(self, *, instrument_id: int = 1) -> None:
        self.instrument_id = instrument_id
        self.calls: list[dict[str, object]] = []

    def get_by_key(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "artifact": {
                "factorExposureKey": RATE_KEY,
                "instrumentId": self.instrument_id,
                "rateSeriesId": "DGS10",
                "asOf": AS_OF,
                "availableAt": AVAILABLE_AT,
                "factors": {"rates": -0.35},
            }
        }


class _Unused:
    def get(self, **_: object) -> None:
        return None


def _install(monkeypatch, *, rates: _Rates | None = None) -> tuple[_Service, _Rates]:
    service = _Service()
    rates_repo = rates or _Rates()
    monkeypatch.setattr(api, "factor_risk_service", service)
    monkeypatch.setattr(api, "_reconciliation_repository", _Reconciliation())
    monkeypatch.setattr(api, "_valuation_repository", _Valuation())
    monkeypatch.setattr(api, "_weight_service", _Weights())
    monkeypatch.setattr(api, "_factor_exposure_repository", _Market())
    monkeypatch.setattr(api, "_price_factor_repository", _Unused())
    monkeypatch.setattr(api, "_size_factor_repository", _Unused())
    monkeypatch.setattr(api, "_rate_factor_repository", rates_repo)
    return service, rates_repo


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
                "rateExposureKey": RATE_KEY,
                "exposureAvailableAt": AVAILABLE_AT,
                "source": "pit_factor_store",
                "sourceRef": "factor:1",
                "factors": {},
            }
        ],
    }


def test_factor_risk_consumes_sealed_rates_artifact(monkeypatch) -> None:
    service, rates = _install(monkeypatch)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_request(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stateIntegrity"]["rateExposureKeys"] == {"1": RATE_KEY}
    assert data["stateIntegrity"]["callerSuppliedRatesAccepted"] is False
    assert data["stateIntegrity"]["rateFactorDerivation"] == (
        "sealed_pit_macro_and_market_observations_or_explicitly_missing"
    )
    evaluated = service.calls[0]["positions"][0]  # type: ignore[index]
    assert evaluated.factors["rates"] == -0.35
    assert evaluated.factors["market"] == 1.0
    assert len(rates.calls) == 1


def test_factor_risk_rejects_caller_supplied_rates(monkeypatch) -> None:
    service, rates = _install(monkeypatch)
    body = _request()
    body["positions"][0]["rateExposureKey"] = None  # type: ignore[index]
    body["positions"][0]["factors"]["rates"] = 9.0  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=body,
    )
    assert response.status_code == 400
    assert "factores sellados" in response.json()["detail"]
    assert service.calls == []
    assert rates.calls == []


def test_factor_risk_rejects_rate_artifact_for_other_instrument(monkeypatch) -> None:
    service, _ = _install(monkeypatch, rates=_Rates(instrument_id=2))
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_request(),
    )
    assert response.status_code == 400
    assert "otro instrumento/asOf" in response.json()["detail"]
    assert service.calls == []

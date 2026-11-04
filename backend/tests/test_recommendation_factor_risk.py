from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_factor_risk as factor_risk_api
from app.main import app
from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
MARKET_KEY = "a" * 64


def _position(
    *,
    instrument_id: int = 1,
    symbol: str = "AAA",
    weight: float = 0.6,
    factors: dict[str, float] | None = None,
    available_at: datetime = AVAILABLE_AT,
    source: str = "athena_factor_model_v1",
    source_ref: str = "factor-snapshot:AAA:2025-12-31",
) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        weight=weight,
        exposure_available_at=available_at,
        source=source,
        source_ref=source_ref,
        factors=factors or {"market": 1.0, "usd_fx": 0.2},
    )


class _ValidReconciliationRepository:
    def require_reconciled(self, **kwargs: object) -> dict[str, object]:
        return {"portfolio_state_key": "d" * 64, "artifact": {"reconciled": True}}


class _ValidValuationRepository:
    def get(self, **kwargs: object) -> dict[str, object]:
        return {
            "artifact": {
                "portfolioValuationEvidenceFingerprint": "c" * 64,
                "positions": [
                    {
                        "instrumentId": 1,
                        "instrumentCurrency": "USD",
                        "fx": {
                            "rate": 1.0,
                            "observedAt": AVAILABLE_AT.isoformat(),
                            "retrievedAt": AVAILABLE_AT.isoformat(),
                            "historicalPointInTimeEligible": True,
                        },
                    }
                ],
            }
        }

    def validate_record(self, record: dict[str, object]) -> dict[str, object]:
        return record


class _ValidWeightService:
    def build(self, **kwargs: object) -> dict[str, object]:
        return {
            "portfolioId": "portfolio-1",
            "reportingCurrency": "USD",
            "asOf": AS_OF.isoformat(),
            "reconciliationKey": "e" * 64,
            "portfolioStateKey": "d" * 64,
            "portfolioValuationEvidenceFingerprint": "c" * 64,
            "weightEvidenceKey": "f" * 64,
            "cashWeight": 0.5,
            "positions": [{"instrumentId": 1, "symbol": "AAA", "weight": 0.5}],
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


class _ValidFactorExposureRepository:
    def get(self, **kwargs: object) -> dict[str, object]:
        return {
            "artifact": {
                "factorExposureKey": MARKET_KEY,
                "instrumentId": 1,
                "benchmarkInstrumentId": 99,
                "asOf": AS_OF.isoformat(),
                "availableAt": AVAILABLE_AT.isoformat(),
                "factors": {"market": 1.0},
            }
        }


def _install_api_evidence(monkeypatch) -> None:
    monkeypatch.setattr(factor_risk_api, "_reconciliation_repository", _ValidReconciliationRepository())
    monkeypatch.setattr(factor_risk_api, "_valuation_repository", _ValidValuationRepository())
    monkeypatch.setattr(factor_risk_api, "_weight_service", _ValidWeightService())
    monkeypatch.setattr(factor_risk_api, "_factor_exposure_repository", _ValidFactorExposureRepository())


def _api_request(*, exposure_available_at: str) -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "e" * 64,
        "portfolioValuationEvidenceFingerprint": "c" * 64,
        "asOf": AS_OF.isoformat(),
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "marketExposureKey": MARKET_KEY,
                "exposureAvailableAt": exposure_available_at,
                "source": "athena_factor_model_v1",
                "sourceRef": "factor-snapshot:AAA:2025-12-31",
                "factors": {},
            }
        ],
    }


def test_factor_risk_aggregates_explicit_pit_portfolio_exposures() -> None:
    service = RecommendationFactorRiskService()
    result = service.evaluate(
        as_of=AS_OF,
        positions=(
            _position(),
            _position(
                instrument_id=2,
                symbol="BBB",
                weight=0.3,
                factors={"market": 0.5, "momentum": 0.4},
                source_ref="factor-snapshot:BBB:2025-12-31",
            ),
        ),
    )
    payload = result.to_api_dict()
    assert payload["positionCount"] == 2
    assert payload["investedWeight"] == pytest.approx(0.9)
    assert payload["cashWeight"] == pytest.approx(0.1)
    assert payload["weightedExposures"]["market"] == pytest.approx(0.75)
    assert payload["weightedExposures"]["quality"] == pytest.approx(0.0)
    assert payload["weightedExposures"]["momentum"] == pytest.approx(0.12)
    assert payload["weightedExposures"]["usd_fx"] == pytest.approx(0.12)
    assert payload["dominantFactor"] == "market"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False


def test_factor_risk_rejects_lookahead_and_non_finite_data() -> None:
    service = RecommendationFactorRiskService()
    with pytest.raises(ValueError, match="look-ahead"):
        service.evaluate(as_of=AS_OF, positions=(_position(available_at=AS_OF + timedelta(microseconds=1)),))
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finito"):
            service.evaluate(as_of=AS_OF, positions=(_position(weight=value),))
        with pytest.raises(ValueError, match="finito"):
            service.evaluate(as_of=AS_OF, positions=(_position(factors={"market": value}),))


def test_factor_risk_rejects_duplicate_identity_missing_provenance_and_unknown_factor() -> None:
    service = RecommendationFactorRiskService()
    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate(as_of=AS_OF, positions=(_position(), _position(instrument_id=1, symbol="BBB", weight=0.2)))
    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate(as_of=AS_OF, positions=(_position(), _position(instrument_id=2, symbol="aaa", weight=0.2)))
    with pytest.raises(ValueError, match="source.*provenance"):
        service.evaluate(as_of=AS_OF, positions=(_position(source=" "),))
    with pytest.raises(ValueError, match="source_ref.*provenance"):
        service.evaluate(as_of=AS_OF, positions=(_position(source_ref=""),))
    with pytest.raises(ValueError, match="Factor no soportado"):
        service.evaluate(as_of=AS_OF, positions=(_position(factors={"astrology": 1.0}),))


def test_factor_risk_rejects_invalid_weight_sum_and_naive_timestamps() -> None:
    service = RecommendationFactorRiskService()
    with pytest.raises(ValueError, match="suma de weights"):
        service.evaluate(as_of=AS_OF, positions=(_position(weight=0.7), _position(instrument_id=2, symbol="BBB", weight=0.4)))
    with pytest.raises(ValueError, match="as_of.*zona horaria"):
        service.evaluate(as_of=datetime(2026, 1, 1), positions=(_position(),))
    with pytest.raises(ValueError, match="exposure_available_at.*zona horaria"):
        service.evaluate(as_of=AS_OF, positions=(_position(available_at=datetime(2025, 12, 31, 23)),))


def test_factor_risk_api_exposes_research_only_contract(monkeypatch) -> None:
    _install_api_evidence(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_api_request(exposure_available_at=AVAILABLE_AT.isoformat()),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["weightedExposures"]["market"] == pytest.approx(0.5)
    assert data["weightedExposures"]["usd_fx"] == pytest.approx(0.0)
    assert data["cashWeight"] == pytest.approx(0.5)
    assert data["policy"]["automaticTrading"] is False
    assert data["stateIntegrity"]["reconciled"] is True
    assert data["stateIntegrity"]["gate"] == "required_before_factor_risk"
    assert data["stateIntegrity"]["weightDerivation"] == "derived_from_reconciled_state_and_sealed_pit_valuation"
    assert data["stateIntegrity"]["marketFactorDerivation"] == "sealed_pit_market_observations_only"
    assert data["stateIntegrity"]["usdFxFactorDerivation"] == "sealed_portfolio_valuation_translation_exposure_or_explicitly_missing"
    assert data["stateIntegrity"]["callerSuppliedMarketAccepted"] is False
    assert data["stateIntegrity"]["callerSuppliedUsdFxAccepted"] is False
    assert data["stateIntegrity"]["marketExposureKeys"]["1"] == MARKET_KEY
    assert data["stateIntegrity"]["callerSuppliedWeightAccepted"] is False
    assert data["stateIntegrity"]["weightEvidenceKey"] == "f" * 64


def test_factor_risk_api_rejects_naive_temporal_evidence_before_service_use(monkeypatch) -> None:
    _install_api_evidence(monkeypatch)
    client = TestClient(app)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=_api_request(exposure_available_at="2025-12-31T23:00:00"),
    )
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_reconciled_portfolio_weights as api_module
from app.api.auth import current_account
from app.main import app
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


AS_OF = "2026-09-01T12:00:00+00:00"


def reconciliation_record() -> dict[str, object]:
    return {
        "portfolio_state_key": "b" * 64,
        "artifact": {
            "reconciliationKey": "a" * 64,
            "portfolioStateKey": "b" * 64,
            "portfolioId": "portfolio-1",
            "reportingCurrency": "USD",
            "asOf": AS_OF,
            "snapshotObservedAt": AS_OF,
            "snapshotAvailableAt": AS_OF,
            "reconciled": True,
            "cashDifference": 0.0,
            "positionMismatches": [],
            "snapshotProvenance": {
                "source": "independent_broker_snapshot",
                "sourceRef": "urn:broker:portfolio-1:2026-09-01",
            },
            "snapshotState": {
                "cashBalance": 100.0,
                "positions": [
                    {"instrumentId": "1", "quantity": 2.0},
                    {"instrumentId": "2", "quantity": 1.0},
                ],
                "observedAt": AS_OF,
                "availableAt": AS_OF,
                "source": "independent_broker_snapshot",
                "sourceRef": "urn:broker:portfolio-1:2026-09-01",
            },
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "stateMismatchAction": "fail_closed",
                "cashInference": "forbidden",
                "fxInference": "forbidden",
                "snapshotRequired": True,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        },
    }


def valuation_record() -> dict[str, object]:
    positions = [
        {
            "instrumentId": 1,
            "symbol": "AAA",
            "canonicalIdentity": {"canonicalInstrumentId": "AAA.US"},
            "quantity": 2.0,
            "positionValueInBaseCurrency": 200.0,
            "price": 100.0,
            "priceSourceProvider": "yahoo",
            "priceObservedAt": "2026-09-01T11:00:00+00:00",
            "priceRetrievedAt": "2026-09-01T11:30:00+00:00",
            "fx": {
                "rate": 1.0,
                "sourceProvider": "identity",
                "observedAt": "2026-09-01T11:00:00+00:00",
                "retrievedAt": "2026-09-01T11:00:00+00:00",
            },
        },
        {
            "instrumentId": 2,
            "symbol": "BBB",
            "canonicalIdentity": {"canonicalInstrumentId": "BBB.US"},
            "quantity": 1.0,
            "positionValueInBaseCurrency": 100.0,
            "price": 100.0,
            "priceSourceProvider": "yahoo",
            "priceObservedAt": "2026-09-01T11:00:00+00:00",
            "priceRetrievedAt": "2026-09-01T11:30:00+00:00",
            "fx": {
                "rate": 1.0,
                "sourceProvider": "identity",
                "observedAt": "2026-09-01T11:00:00+00:00",
                "retrievedAt": "2026-09-01T11:00:00+00:00",
            },
        },
    ]
    return {
        "valuation_fingerprint": "c" * 64,
        "artifact": {
            "status": "portfolio_valuation_evidence_verified_non_advisory",
            "portfolioValuationEvidenceReady": True,
            "portfolioValuationEvidenceFingerprint": "c" * 64,
            "asOf": AS_OF,
            "baseCurrency": "USD",
            "cashIncluded": False,
            "liabilitiesIncluded": False,
            "positionCount": 2,
            "positions": positions,
            "investedPositionsValueInBaseCurrency": 300.0,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "automaticTrading": False,
        },
    }


def test_weights_are_derived_from_reconciled_cash_quantities_and_pit_valuation() -> None:
    service = RecommendationReconciledPortfolioWeightService()
    result = service.build(
        reconciliation_record=reconciliation_record(),
        valuation_record=valuation_record(),
    )

    assert result["cashBalance"] == 100.0
    assert result["investedPositionsValue"] == 300.0
    assert result["totalPortfolioValue"] == 400.0
    assert result["cashWeight"] == pytest.approx(0.25)
    assert result["positions"][0]["weight"] == pytest.approx(0.50)
    assert result["positions"][1]["weight"] == pytest.approx(0.25)
    assert sum(item["weight"] for item in result["positions"]) + result["cashWeight"] == pytest.approx(1.0)
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["allocationEligible"] is False
    assert result["policy"]["cash"] == "from_independent_reconciled_snapshot_never_inferred"
    assert result["policy"]["fx"] == "from_sealed_pit_valuation_never_implicitly_converted"
    assert len(result["weightEvidenceKey"]) == 64
    assert service.validate_artifact(result) is result


def test_weights_fail_closed_on_quantity_identity_currency_and_time_mismatch() -> None:
    service = RecommendationReconciledPortfolioWeightService()

    valuation = valuation_record()
    valuation["artifact"]["positions"][0]["quantity"] = 3.0  # type: ignore[index]
    with pytest.raises(ValueError, match="cantidad valorada"):
        service.build(reconciliation_record=reconciliation_record(), valuation_record=valuation)

    valuation = valuation_record()
    valuation["artifact"]["positions"].pop()  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="identity mismatch"):
        service.build(reconciliation_record=reconciliation_record(), valuation_record=valuation)

    valuation = valuation_record()
    valuation["artifact"]["baseCurrency"] = "EUR"  # type: ignore[index]
    with pytest.raises(ValueError, match="otra moneda"):
        service.build(reconciliation_record=reconciliation_record(), valuation_record=valuation)

    valuation = valuation_record()
    valuation["artifact"]["asOf"] = "2026-08-31T12:00:00+00:00"  # type: ignore[index]
    with pytest.raises(ValueError, match="exactamente"):
        service.build(reconciliation_record=reconciliation_record(), valuation_record=valuation)


def test_weights_reject_non_finite_late_snapshot_fmp_and_unsafe_contract() -> None:
    service = RecommendationReconciledPortfolioWeightService()

    reconciliation = reconciliation_record()
    reconciliation["artifact"]["snapshotState"]["cashBalance"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValueError, match="no negativo y finito"):
        service.build(reconciliation_record=reconciliation, valuation_record=valuation_record())

    reconciliation = reconciliation_record()
    reconciliation["artifact"]["snapshotState"]["availableAt"] = "2026-09-02T12:00:00+00:00"  # type: ignore[index]
    with pytest.raises(ValueError, match="PIT/no-lookahead"):
        service.build(reconciliation_record=reconciliation, valuation_record=valuation_record())

    valuation = valuation_record()
    valuation["artifact"]["positions"][0]["priceSourceProvider"] = "Financial Modeling Prep"  # type: ignore[index]
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        service.build(reconciliation_record=reconciliation_record(), valuation_record=valuation)

    reconciliation = reconciliation_record()
    reconciliation["artifact"]["isWeightingReady"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="producción/weighting"):
        service.build(reconciliation_record=reconciliation, valuation_record=valuation_record())


def test_weight_evidence_hash_detects_tampering() -> None:
    service = RecommendationReconciledPortfolioWeightService()
    result = service.build(
        reconciliation_record=reconciliation_record(),
        valuation_record=valuation_record(),
    )
    result["positions"][0]["weight"] = 0.9
    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(result)


class _ReconciliationRepository:
    def get_by_key(self, **kwargs: object) -> dict[str, object]:
        return reconciliation_record()


class _ValuationRepository:
    def get(self, **kwargs: object) -> dict[str, object]:
        return valuation_record()

    def validate_record(self, record: dict[str, object]) -> dict[str, object]:
        return record


class _OwnershipRegistry:
    def require_current_owner(self, **kwargs: object) -> None:
        return None

    def link_current_owner(self, **kwargs: object) -> None:
        return None


def test_reconciled_weights_api_is_registered_and_research_only(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "_reconciliation_repository", _ReconciliationRepository())
    monkeypatch.setattr(api_module, "_valuation_repository", _ValuationRepository())
    monkeypatch.setattr(api_module, "_ownership", _OwnershipRegistry())
    app.dependency_overrides[current_account] = lambda: {"id": 1}
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/recommendations/professional-research/reconciled-portfolio-weights",
                json={
                    "reconciliationKey": "a" * 64,
                    "portfolioValuationEvidenceFingerprint": "c" * 64,
                },
            )
    finally:
        app.dependency_overrides.pop(current_account, None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["module"] == "reconciled_portfolio_weights"
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["allocationEligible"] is False
    assert data["cashWeight"] == pytest.approx(0.25)
    assert len(data["weightEvidenceKey"]) == 64

    assert (
        "/api/v1/recommendations/professional-research/reconciled-portfolio-weights"
        in app.openapi()["paths"]
    )

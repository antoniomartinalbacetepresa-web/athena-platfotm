from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_professional_dossier_service import RecommendationProfessionalDossierService


class FakeProductionReadService:
    def __init__(self, state):
        self.state = state

    def resolve_latest(self, **kwargs):
        return self.state


def _state(*, recommendation=True, allocation=False):
    rec = None
    if recommendation:
        rec = {
            "instrumentId": "7",
            "symbol": "AAPL",
            "action": "buy",
            "policyState": "flat",
            "horizonDays": 30,
            "expectedExcessReturn": 0.0425,
            "authorizationReason": "Revisión humana sobre evidencia OOS sellada.",
            "authorizationFingerprint": "a" * 64,
            "economicContractFingerprint": "b" * 64,
            "asOf": "2026-09-01T11:00:00+00:00",
            "authorizedAt": "2026-09-01T11:30:00+00:00",
        }
    alloc = {"authorizationFingerprint": "c" * 64} if allocation else None
    return {
        "symbol": None,
        "instrumentId": None,
        "recommendation": rec,
        "allocation": alloc,
        "productionRecommendationAvailable": rec is not None,
        "productionAllocationAvailable": alloc is not None,
        "automaticTrading": False,
        "readOnly": True,
    }


def _service(state):
    return RecommendationProfessionalDossierService(production_read_service=FakeProductionReadService(state))


def test_no_production_recommendation_stays_no_advice_and_marks_gaps() -> None:
    result = _service(_state(recommendation=False)).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    assert result["decision"] is None
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False
    assert all(module["status"] == "not_yet_evidenced" for module in result["professionalModules"].values())


def test_production_dossier_preserves_only_sealed_decision_evidence() -> None:
    result = _service(_state()).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    assert result["decision"]["action"] == "buy"
    assert result["decision"]["horizonDays"] == 30
    assert result["decision"]["expectedExcessReturn"] == 0.0425
    assert result["evidence"]["oosCalibrationBound"] is True
    assert result["evidence"]["precommittedUncertaintyGateBound"] is True
    assert result["evidence"]["expectedExcessReturnIsProbability"] is False
    assert result["executionEligible"] is False
    assert result["orderRoutingEligible"] is False
    assert result["automaticTrading"] is False


def test_allocation_is_reported_separately_and_never_enables_execution() -> None:
    result = _service(_state(allocation=True)).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    assert result["allocationEligible"] is True
    assert result["evidence"]["productionAllocationAuthorized"] is True
    assert result["evidence"]["allocationExecutionEligible"] is False
    assert result["executionEligible"] is False
    assert result["automaticTrading"] is False


def test_rejects_non_finite_productive_signal() -> None:
    state = _state()
    state["recommendation"]["expectedExcessReturn"] = float("nan")
    with pytest.raises(ValueError, match="finito"):
        _service(state).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))


def test_rejects_unsafe_or_internally_inconsistent_state() -> None:
    unsafe = _state()
    unsafe["automaticTrading"] = True
    with pytest.raises(ValueError, match="seguro"):
        _service(unsafe).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))

    inconsistent = _state(recommendation=False)
    inconsistent["productionRecommendationAvailable"] = True
    with pytest.raises(ValueError, match="contradice"):
        _service(inconsistent).build(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))


def test_requires_timezone_aware_cutoff() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        _service(_state()).build(as_of=datetime(2026, 9, 1, 12))

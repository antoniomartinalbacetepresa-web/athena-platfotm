from datetime import datetime, timezone

import pytest

from app.services.sec_free_cash_flow_service import SecFreeCashFlowService


AS_OF = datetime(2026, 3, 1, tzinfo=timezone.utc)


class _Resolver:
    def __init__(self, *, ocf=None, capex=None):
        self.ocf = ocf
        self.capex = capex

    def resolve(self, *, cik, canonical_concept, as_of):
        fact = self.ocf if canonical_concept == "operating_cash_flow_annual" else self.capex
        return {
            "status": "resolved" if fact is not None else "missing",
            "cik": "0000123456",
            "asOf": as_of.isoformat(),
            "selectedFact": fact,
            "productionEligible": False,
        }


def _fact(value, *, start="2025-01-01", end="2025-12-31", unit="USD", concept="Fact"):
    return {
        "factKey": "a" * 64,
        "concept": concept,
        "unit": unit,
        "value": value,
        "periodStart": start,
        "periodEnd": end,
        "availableAt": "2026-02-01T12:00:00+00:00",
        "provenance": {"source": "sec_edgar", "sourceRef": "sec:test"},
    }


def test_fcf_requires_same_period_and_computes_ocf_minus_capex() -> None:
    result = SecFreeCashFlowService(_Resolver(
        ocf=_fact(500.0, concept="NetCashProvidedByUsedInOperatingActivities"),
        capex=_fact(125.0, concept="PaymentsToAcquirePropertyPlantAndEquipment"),
    )).evaluate(cik="123456", as_of=AS_OF)

    assert result.status == "diagnostic_ready"
    assert result.free_cash_flow == pytest.approx(375.0)
    assert result.unit == "USD"
    assert result.period_end == "2025-12-31"
    assert result.production_eligible is False


def test_fcf_fails_closed_on_period_mismatch() -> None:
    result = SecFreeCashFlowService(_Resolver(
        ocf=_fact(500.0),
        capex=_fact(125.0, start="2024-01-01", end="2024-12-31"),
    )).evaluate(cik="123456", as_of=AS_OF)

    assert result.status == "period_mismatch"
    assert result.free_cash_flow is None


def test_fcf_fails_closed_when_component_is_missing() -> None:
    result = SecFreeCashFlowService(_Resolver(ocf=_fact(500.0), capex=None)).evaluate(cik="123456", as_of=AS_OF)

    assert result.status == "evidence_missing"
    assert result.free_cash_flow is None
    assert result.production_eligible is False


def test_fcf_rejects_naive_cutoff() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        SecFreeCashFlowService(_Resolver()).evaluate(cik="123456", as_of=datetime(2026, 3, 1))

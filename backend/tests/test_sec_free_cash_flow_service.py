from datetime import datetime, timezone

import pytest

from app.services.sec_free_cash_flow_service import SecFreeCashFlowService


AS_OF = datetime(2026, 3, 1, tzinfo=timezone.utc)


class _Resolver:
    def __init__(self, *, ocf=None, capex=None, shares=None):
        self.ocf = ocf
        self.capex = capex
        self.shares = shares

    def resolve(self, *, cik, canonical_concept, as_of):
        fact = {
            "operating_cash_flow_annual": self.ocf,
            "capital_expenditure_annual": self.capex,
            "diluted_shares_annual": self.shares,
        }[canonical_concept]
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
        shares=_fact(100.0, unit="shares", concept="WeightedAverageNumberOfDilutedSharesOutstanding"),
    )).evaluate(cik="123456", as_of=AS_OF)

    assert result.status == "diagnostic_ready"
    assert result.free_cash_flow == pytest.approx(375.0)
    assert result.unit == "USD"
    assert result.period_end == "2025-12-31"
    assert result.free_cash_flow_per_share == pytest.approx(3.75)
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


def test_fcf_per_share_fails_closed_when_diluted_shares_period_differs() -> None:
    result = SecFreeCashFlowService(_Resolver(
        ocf=_fact(500.0),
        capex=_fact(125.0),
        shares=_fact(100.0, start="2024-01-01", end="2024-12-31", unit="shares"),
    )).evaluate(cik="123456", as_of=AS_OF)

    assert result.status == "diagnostic_ready"
    assert result.free_cash_flow == pytest.approx(375.0)
    assert result.free_cash_flow_per_share is None


def test_fcf_per_share_requires_positive_share_denominator() -> None:
    result = SecFreeCashFlowService(_Resolver(
        ocf=_fact(500.0),
        capex=_fact(125.0),
        shares=_fact(0.0, unit="shares"),
    )).evaluate(cik="123456", as_of=AS_OF)

    assert result.free_cash_flow == pytest.approx(375.0)
    assert result.free_cash_flow_per_share is None

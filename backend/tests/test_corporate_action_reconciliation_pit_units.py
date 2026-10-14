"""Fail-closed PIT and economic-unit regression tests for corporate actions."""
from datetime import datetime, timezone

import pytest

from app.services.corporate_action_reconciliation_service import (
    CorporateActionReconciliationService,
)

CUTOFF = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_for_instrument(self, instrument_id, *, source_provider, knowledge_cutoff):
        assert instrument_id == 19
        assert knowledge_cutoff == CUTOFF
        return self.rows.get(source_provider, [])


def _row(provider, *, action_type="dividend", effective_at="2026-08-15T00:00:00+00:00",
         retrieved_at="2026-09-10T10:00:00+00:00", cash_amount=0.25,
         split_ratio=None, currency="USD"):
    return {
        "source_provider": provider,
        "action_type": action_type,
        "effective_at": effective_at,
        "retrieved_at": retrieved_at,
        "cash_amount": cash_amount,
        "split_ratio": split_ratio,
        "currency": currency,
    }


def _reconcile(primary, secondary):
    return CorporateActionReconciliationService(
        repository=FakeRepository({"yahoo": [primary], "alpha_vantage": [secondary]})
    ).reconcile(
        instrument_id=19,
        source_providers=["yahoo", "alpha_vantage"],
        knowledge_cutoff=CUTOFF,
    )


def test_equivalent_effective_instants_with_different_offsets_agree():
    report = _reconcile(
        _row("yahoo"),
        _row("alpha_vantage", effective_at="2026-08-15T02:00:00+02:00"),
    )
    assert report.reconciled
    assert report.agreed_event_count == 1
    assert report.events[0].effective_at == "2026-08-15T00:00:00+00:00"


@pytest.mark.parametrize("effective", ["not-a-date", "2026-08-15T00:00:00"])
def test_invalid_or_naive_effective_instant_is_rejected(effective):
    with pytest.raises(RuntimeError, match="effective_at"):
        _reconcile(_row("yahoo", effective_at=effective), _row("alpha_vantage"))


def test_future_effective_instant_leaked_by_repository_is_rejected():
    with pytest.raises(RuntimeError, match="knowledge cutoff PIT"):
        _reconcile(
            _row("yahoo", effective_at="2026-10-01T00:00:00+00:00"),
            _row("alpha_vantage"),
        )


@pytest.mark.parametrize("currency", [None, "", "EURO", "€UR", "US1", 123])
def test_dividend_requires_explicit_valid_currency(currency):
    with pytest.raises(RuntimeError, match="currency"):
        _reconcile(
            _row("yahoo", currency=currency),
            _row("alpha_vantage", currency=currency),
        )


@pytest.mark.parametrize("amount", [float("inf"), float("nan"), -0.1, 0, True, "oops", None])
def test_dividend_amount_must_be_positive_finite(amount):
    with pytest.raises(RuntimeError, match="cash_amount"):
        _reconcile(
            _row("yahoo", cash_amount=amount),
            _row("alpha_vantage", cash_amount=amount),
        )


@pytest.mark.parametrize("ratio", [float("inf"), float("nan"), -2, 0, True, "oops", None])
def test_split_ratio_must_be_positive_finite(ratio):
    with pytest.raises(RuntimeError, match="split_ratio"):
        _reconcile(
            _row("yahoo", action_type="split", cash_amount=None, split_ratio=ratio),
            _row("alpha_vantage", action_type="split", cash_amount=None, split_ratio=ratio),
        )


def test_dividend_with_different_currencies_is_conflict():
    report = _reconcile(_row("yahoo", currency="USD"), _row("alpha_vantage", currency="EUR"))
    assert not report.reconciled
    assert report.conflict_event_count == 1


def test_dividend_currency_case_is_normalized():
    report = _reconcile(_row("yahoo", currency="usd"), _row("alpha_vantage", currency="USD"))
    assert report.reconciled


def test_superseded_nonfinite_snapshot_cannot_hide_behind_valid_revision():
    service = CorporateActionReconciliationService(
        repository=FakeRepository({
            "yahoo": [
                _row("yahoo", cash_amount=float("inf"), retrieved_at="2026-09-01T10:00:00+00:00"),
                _row("yahoo"),
            ],
            "alpha_vantage": [_row("alpha_vantage")],
        })
    )
    with pytest.raises(RuntimeError, match="cash_amount"):
        service.reconcile(
            instrument_id=19,
            source_providers=["yahoo", "alpha_vantage"],
            knowledge_cutoff=CUTOFF,
        )


def test_valid_split_remains_diagnostic_only():
    report = _reconcile(
        _row("yahoo", action_type="split", cash_amount=None, split_ratio=4.0, currency=None),
        _row("alpha_vantage", action_type="split", cash_amount=None, split_ratio=4.0, currency=None),
    )
    assert report.reconciled
    assert report.to_api_dict()["automaticCanonicalization"] is False

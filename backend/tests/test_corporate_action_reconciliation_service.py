from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.corporate_action_reconciliation_service import (
    CorporateActionReconciliationService,
)


CUTOFF = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, rows_by_provider):
        self.rows_by_provider = rows_by_provider
        self.calls = []

    def list_for_instrument(
        self,
        instrument_id,
        *,
        source_provider=None,
        knowledge_cutoff=None,
        effective_from=None,
        effective_to=None,
    ):
        self.calls.append(
            {
                "instrument_id": instrument_id,
                "source_provider": source_provider,
                "knowledge_cutoff": knowledge_cutoff,
                "effective_from": effective_from,
                "effective_to": effective_to,
            }
        )
        return [dict(row) for row in self.rows_by_provider.get(source_provider, [])]


def _dividend(provider, amount=0.25, currency="usd", retrieved_at="2026-09-10T10:00:00+00:00"):
    return {
        "action_type": "dividend",
        "effective_at": "2026-08-15T00:00:00+00:00",
        "cash_amount": amount,
        "split_ratio": None,
        "currency": currency,
        "source_provider": provider,
        "retrieved_at": retrieved_at,
    }


def _split(provider, ratio=4.0, retrieved_at="2026-09-10T10:00:00+00:00"):
    return {
        "action_type": "split",
        "effective_at": "2026-07-01T00:00:00+00:00",
        "cash_amount": None,
        "split_ratio": ratio,
        "currency": None,
        "source_provider": provider,
        "retrieved_at": retrieved_at,
    }


def test_reconciliation_requires_two_distinct_providers_and_aware_cutoff():
    service = CorporateActionReconciliationService(repository=FakeRepository({}))

    with pytest.raises(ValueError, match="al menos dos"):
        service.reconcile(instrument_id=1, source_providers=["yahoo_finance"], knowledge_cutoff=CUTOFF)
    with pytest.raises(ValueError, match="duplicados"):
        service.reconcile(instrument_id=1, source_providers=["yahoo_finance", "yahoo_finance"], knowledge_cutoff=CUTOFF)
    with pytest.raises(ValueError, match="zona horaria"):
        service.reconcile(instrument_id=1, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=datetime(2026, 9, 11, 10, 0))


def test_reconciliation_forwards_same_pit_cutoff_to_each_provider():
    repository = FakeRepository({"yahoo_finance": [], "secondary": []})
    service = CorporateActionReconciliationService(repository=repository)
    report = service.reconcile(instrument_id=42, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is False
    assert report.events == ()
    assert [call["knowledge_cutoff"] for call in repository.calls] == [CUTOFF, CUTOFF]


def test_matching_dividend_and_split_are_reconciled_without_auto_canonicalization():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance"), _split("yahoo_finance")], "secondary": [_dividend("secondary", currency="USD"), _split("secondary")]})
    report = CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=7, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is True
    assert report.agreed_event_count == 2
    assert report.conflict_event_count == 0
    assert report.incomplete_event_count == 0
    payload = report.to_api_dict()
    assert payload["reconciled"] is True
    assert payload["automaticCanonicalization"] is False
    assert all(event["status"] == "agreed" for event in payload["events"])


def test_conflicting_values_fail_closed_instead_of_selecting_a_provider():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance", amount=0.25)], "secondary": [_dividend("secondary", amount=0.30)]})
    report = CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=7, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is False
    assert report.conflict_event_count == 1
    assert report.events[0].status == "conflict"


def test_missing_provider_is_incomplete_not_agreed():
    repository = FakeRepository({"yahoo_finance": [_split("yahoo_finance")], "secondary": []})
    report = CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=9, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is False
    assert report.incomplete_event_count == 1
    assert report.events[0].providers_missing == ("secondary",)


def test_latest_visible_snapshot_per_provider_is_used_for_comparison():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance", amount=0.20, retrieved_at="2026-09-01T10:00:00+00:00"), _dividend("yahoo_finance", amount=0.25, retrieved_at="2026-09-10T10:00:00+00:00")], "secondary": [_dividend("secondary", amount=0.25)]})
    report = CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=11, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is True
    assert report.events[0].values_by_provider["yahoo_finance"]["cashAmount"] == 0.25


def test_invalid_persisted_contract_fails_closed():
    repository = FakeRepository({"yahoo_finance": [{"action_type": "merger", "effective_at": "2026-08-15T00:00:00+00:00", "retrieved_at": "2026-09-10T10:00:00+00:00"}], "secondary": []})
    with pytest.raises(RuntimeError, match="contrato inválido"):
        CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=5, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)


def test_provider_query_cannot_reconcile_row_with_mismatched_provenance():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance")], "secondary": [_dividend("yahoo_finance")]})
    with pytest.raises(RuntimeError, match="provenance incompatible"):
        CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=13, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)


def test_missing_persisted_provider_cannot_count_as_secondary_evidence():
    row = _split("secondary")
    row["source_provider"] = None
    repository = FakeRepository({"yahoo_finance": [_split("yahoo_finance")], "secondary": [row]})
    with pytest.raises(RuntimeError, match="provenance incompatible"):
        CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=14, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)


def test_repository_cannot_leak_future_snapshot_past_pit_cutoff():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance", retrieved_at="2026-09-12T10:00:00+00:00")], "secondary": [_dividend("secondary")]})
    with pytest.raises(RuntimeError, match="knowledge cutoff PIT"):
        CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=15, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)


def test_persisted_retrieved_at_requires_valid_aware_timestamp():
    for retrieved_at in ("not-a-date", "2026-09-10T10:00:00"):
        repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance", retrieved_at=retrieved_at)], "secondary": []})
        with pytest.raises(RuntimeError, match="retrieved_at"):
            CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=16, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)


def test_latest_snapshot_order_uses_datetime_not_lexicographic_text():
    repository = FakeRepository({"yahoo_finance": [_dividend("yahoo_finance", amount=0.20, retrieved_at="2026-09-10T12:00:00+02:00"), _dividend("yahoo_finance", amount=0.25, retrieved_at="2026-09-10T10:30:00+00:00")], "secondary": [_dividend("secondary", amount=0.25, retrieved_at="2026-09-10T10:30:00+00:00")]})
    report = CorporateActionReconciliationService(repository=repository).reconcile(instrument_id=17, source_providers=["yahoo_finance", "secondary"], knowledge_cutoff=CUTOFF)
    assert report.reconciled is True
    assert report.events[0].values_by_provider["yahoo_finance"]["cashAmount"] == 0.25


def test_numeric_tolerance_must_be_finite_and_non_negative():
    with pytest.raises(ValueError):
        CorporateActionReconciliationService(repository=FakeRepository({}), numeric_tolerance=-1)
    with pytest.raises(ValueError):
        CorporateActionReconciliationService(repository=FakeRepository({}), numeric_tolerance=float("nan"))

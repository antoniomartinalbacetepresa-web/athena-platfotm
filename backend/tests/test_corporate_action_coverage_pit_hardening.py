from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.corporate_action_coverage_service import CorporateActionCoverageService


AS_OF = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def _database(tmp_path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type)
            VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'equity')
            """
        )
    return database


def _row(provider: str, *, amount: float, retrieved_at: str) -> dict:
    return {
        "action_type": "dividend",
        "effective_at": "2026-08-15T00:00:00+00:00",
        "cash_amount": amount,
        "split_ratio": None,
        "currency": "USD",
        "source_provider": provider,
        "retrieved_at": retrieved_at,
        "capture_verified": 1,  # synthetic verified marker for PIT leak fixtures
    }


class LeakyRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_for_instrument(self, instrument_id, **kwargs):
        return [dict(row) for row in self.rows]


def _service(tmp_path, rows) -> CorporateActionCoverageService:
    service = CorporateActionCoverageService(
        database=_database(tmp_path),
        provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"},
    )
    service._repository = LeakyRepository(rows)
    return service


def test_aggregate_coverage_rejects_repository_pit_leakage(tmp_path) -> None:
    service = _service(tmp_path, [
        _row("yahoo", amount=0.25, retrieved_at="2026-09-13T08:00:00+00:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
    ])
    with pytest.raises(RuntimeError, match="knowledge cutoff PIT"):
        service.get_report(as_of=AS_OF)


def test_aggregate_snapshot_order_uses_instant_not_timestamp_text(tmp_path) -> None:
    service = _service(tmp_path, [
        _row("yahoo", amount=0.20, retrieved_at="2026-09-11T12:00:00+02:00"),
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T10:30:00+00:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T10:30:00+00:00"),
    ])
    report = service.get_report(as_of=AS_OF)
    assert report.agreed_event_count == 1
    assert report.conflict_event_count == 0
    assert report.cross_provider_reconciliation_ready is True


@pytest.mark.parametrize("retrieved_at", ["not-a-date", "2026-09-11T08:00:00"])
def test_aggregate_coverage_rejects_invalid_retrieved_at(tmp_path, retrieved_at) -> None:
    service = _service(tmp_path, [_row("yahoo", amount=0.25, retrieved_at=retrieved_at)])
    with pytest.raises(RuntimeError, match="retrieved_at"):
        service.get_report(as_of=AS_OF)



def test_distinct_same_time_dividends_persist_but_never_claim_ready(tmp_path) -> None:
    from app.repositories.corporate_action_repository import CorporateActionRepository

    database = _database(tmp_path)
    repository = CorporateActionRepository(database)
    retrieved = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
    actions = [
        {
            "type": "dividend",
            "effectiveAt": "2026-08-15T00:00:00+00:00",
            "cashAmount": amount,
            "currency": "USD",
        }
        for amount in (0.25, 0.10)
    ]
    stats = repository.save_many(
        instrument_id=1, source_provider="yahoo",
        retrieved_at=retrieved, actions=actions,
    )
    assert stats.inserted == 2
    repository.save_many(
        instrument_id=1, source_provider="exchange_notice",
        retrieved_at=retrieved, actions=[actions[0]],
    )
    report = CorporateActionCoverageService(
        database=database,
        provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"},
    ).get_report(as_of=AS_OF)
    assert report.event_count == 1
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.cross_provider_reconciliation_ready is False


def test_same_pit_instant_different_offsets_cannot_hide_ambiguity(tmp_path) -> None:
    service = _service(tmp_path, [
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
        _row("yahoo", amount=0.10, retrieved_at="2026-09-11T10:00:00+02:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
    ])
    report = service.get_report(as_of=AS_OF)
    assert report.agreed_event_count == 0
    assert report.conflict_event_count == 1
    assert report.cross_provider_reconciliation_ready is False


def test_superseded_ambiguous_snapshot_does_not_override_newer_evidence(tmp_path) -> None:
    service = _service(tmp_path, [
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
        _row("yahoo", amount=0.10, retrieved_at="2026-09-11T08:00:00+00:00"),
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T09:00:00+00:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T09:00:00+00:00"),
    ])
    report = service.get_report(as_of=AS_OF)
    assert report.agreed_event_count == 1
    assert report.conflict_event_count == 0
    assert report.cross_provider_reconciliation_ready is True



def test_aggregate_coverage_rejects_future_effective_event_leaked_by_repository(tmp_path) -> None:
    future = _row(
        "yahoo", amount=0.25,
        retrieved_at="2026-09-11T08:00:00+00:00",
    )
    future["effective_at"] = "2026-09-13T00:00:00+00:00"
    service = _service(tmp_path, [future])
    with pytest.raises(RuntimeError, match="knowledge cutoff PIT"):
        service.get_report(as_of=AS_OF)


def test_aggregate_coverage_accepts_effective_instant_exactly_at_cutoff(tmp_path) -> None:
    yahoo = _row(
        "yahoo", amount=0.25,
        retrieved_at="2026-09-11T08:00:00+00:00",
    )
    yahoo["effective_at"] = "2026-09-12T12:00:00+02:00"
    exchange = _row(
        "exchange_notice", amount=0.25,
        retrieved_at="2026-09-11T08:00:00+00:00",
    )
    exchange["effective_at"] = "2026-09-12T10:00:00+00:00"
    report = _service(tmp_path, [yahoo, exchange]).get_report(as_of=AS_OF)
    assert report.agreed_event_count == 1
    assert report.cross_provider_reconciliation_ready is True


def test_missing_capture_marker_cannot_claim_reconciliation_ready(tmp_path) -> None:
    rows = [
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
    ]
    rows[0].pop("capture_verified")
    report = _service(tmp_path, rows).get_report(as_of=AS_OF)
    assert report.agreed_event_count == 1  # diagnostics remain visible
    assert report.unverified_capture_count == 1
    assert report.cross_provider_reconciliation_ready is False


@pytest.mark.parametrize("bad_marker", [None, False, True, "1", 2])
def test_noncanonical_capture_marker_fails_closed(tmp_path, bad_marker) -> None:
    rows = [
        _row("yahoo", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
        _row("exchange_notice", amount=0.25, retrieved_at="2026-09-11T08:00:00+00:00"),
    ]
    rows[0]["capture_verified"] = bad_marker
    report = _service(tmp_path, rows).get_report(as_of=AS_OF)
    assert report.unverified_capture_count == 1
    assert report.cross_provider_reconciliation_ready is False

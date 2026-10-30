from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.verified_corporate_action_secondary_backfill_service import (
    VerifiedCorporateActionSecondaryBackfillService,
)


AS_OF = datetime(2026, 9, 13, 19, 0, tzinfo=timezone.utc)
VERIFIED_AT = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
PRIMARY_RETRIEVED = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
SECONDARY_RETRIEVED = "2026-09-13T19:30:00+00:00"


class FakeAlphaVantageProvider:
    def __init__(self, responses: dict[str, list[dict[str, object]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((symbol, from_date, to_date))
        return list(self.responses.get(symbol, []))


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase, symbol: str) -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type,
                currency, is_active
            ) VALUES (?, ?, 'NASDAQ', 'stock', 'USD', 1)
            """,
            (symbol, symbol),
        )
        return int(cursor.lastrowid)


def _seed_yahoo_dividend(
    database: AthenaDatabase,
    instrument_id: int,
    *,
    effective_at: str,
    amount: float = 0.25,
) -> None:
    CorporateActionRepository(database).save_many(
        instrument_id=instrument_id,
        source_provider="yahoo",
        retrieved_at=PRIMARY_RETRIEVED,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": effective_at,
                "cashAmount": amount,
                "currency": "USD",
            }
        ],
    )


def _alpha_dividend(symbol: str, effective_at: str, amount: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sourceProvider": "alpha_vantage",
        "timestamp": effective_at,
        "retrievedAt": SECONDARY_RETRIEVED,
        "dividend": amount,
        "stockSplit": None,
    }


def test_matching_secondary_event_reduces_incomplete_and_increases_agreement(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAPL")
    effective_at = "2026-08-15T00:00:00+00:00"
    _seed_yahoo_dividend(database, instrument_id, effective_at=effective_at)
    provider = FakeAlphaVantageProvider(
        {"AAPL": [_alpha_dividend("AAPL", effective_at, 0.25)]}
    )

    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFIED_AT,
    ).run(as_of=AS_OF, limit=10)

    assert report.selected_event_count == 1
    assert report.selected_instrument_count == 1
    assert report.persisted_instrument_count == 1
    assert report.incomplete_before == 1
    assert report.incomplete_after == 0
    assert report.selected_events_still_incomplete == 0
    assert report.agreed_before == 0
    assert report.agreed_after == 1
    assert report.conflicts_after == 0
    assert report.status == "targeted_secondary_family_observed"
    assert provider.calls == [("AAPL", "2026-08-08", "2026-09-13")]
    payload = report.to_api_dict()
    assert payload["reconciliation"]["netIncompleteReduced"] == 1
    assert payload["policy"]["automaticCanonicalization"] is False
    assert payload["policy"]["productionIndependenceClaimed"] is False
    assert payload["policy"]["automaticReadinessPromotion"] is False


def test_disagreeing_secondary_event_is_reported_as_conflict_not_resolution(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAPL")
    effective_at = "2026-08-15T00:00:00+00:00"
    _seed_yahoo_dividend(database, instrument_id, effective_at=effective_at, amount=0.25)
    provider = FakeAlphaVantageProvider(
        {"AAPL": [_alpha_dividend("AAPL", effective_at, 0.30)]}
    )

    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFIED_AT,
    ).run(as_of=AS_OF, limit=10)

    assert report.incomplete_before == 1
    assert report.incomplete_after == 0
    assert report.agreed_after == 0
    assert report.conflicts_before == 0
    assert report.conflicts_after == 1
    assert report.status == "targeted_secondary_conflict_detected"
    assert report.to_api_dict()["policy"]["automaticCanonicalization"] is False


def test_no_secondary_action_keeps_targeted_event_incomplete(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAPL")
    effective_at = "2026-08-15T00:00:00+00:00"
    _seed_yahoo_dividend(database, instrument_id, effective_at=effective_at)
    provider = FakeAlphaVantageProvider({"AAPL": []})

    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFIED_AT,
    ).run(as_of=AS_OF, limit=10)

    assert report.no_action_count == 1
    assert report.incomplete_before == 1
    assert report.incomplete_after == 1
    assert report.selected_events_still_incomplete == 1
    assert report.status == "targeted_events_still_incomplete"


def test_limit_targets_only_selected_worklist_instrument(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = _instrument(database, "AAA")
    second = _instrument(database, "BBB")
    first_effective = "2026-07-01T00:00:00+00:00"
    second_effective = "2026-08-01T00:00:00+00:00"
    _seed_yahoo_dividend(database, first, effective_at=first_effective)
    _seed_yahoo_dividend(database, second, effective_at=second_effective)
    provider = FakeAlphaVantageProvider(
        {
            "AAA": [_alpha_dividend("AAA", first_effective, 0.25)],
            "BBB": [_alpha_dividend("BBB", second_effective, 0.25)],
        }
    )

    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFIED_AT,
    ).run(as_of=AS_OF, limit=1, offset=1)

    assert report.selected_event_count == 1
    assert report.selected_instrument_count == 1
    assert [call[0] for call in provider.calls] == ["BBB"]
    assert report.incomplete_before == 2
    assert report.incomplete_after == 1
    assert report.selected_events_still_incomplete == 0


def test_service_requires_timezone_aware_cutoffs(tmp_path: Path) -> None:
    database = _database(tmp_path)
    provider = FakeAlphaVantageProvider({})
    service = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFIED_AT,
    )

    try:
        service.run(as_of=datetime(2026, 9, 13, 19, 0), limit=1)
    except ValueError as exc:
        assert "zona horaria" in str(exc)
    else:
        raise AssertionError("Se esperaba rechazo de as_of sin zona horaria")


def test_sweep_freezes_two_instruments_before_first_resolution(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = _instrument(database, "AAA")
    second = _instrument(database, "BBB")
    effective = "2026-08-15T00:00:00+00:00"
    _seed_yahoo_dividend(database, first, effective_at=effective)
    _seed_yahoo_dividend(database, second, effective_at=effective)
    provider = FakeAlphaVantageProvider({
        "AAA": [_alpha_dividend("AAA", effective, 0.25)],
        "BBB": [_alpha_dividend("BBB", effective, 0.25)],
    })
    result = VerifiedCorporateActionSecondaryBackfillService(
        database=database, history_provider=provider, clock=lambda: VERIFIED_AT,
    ).run_sweep(as_of=AS_OF, limit=1, max_batches=2)

    assert [call[0] for call in provider.calls] == ["AAA", "BBB"]
    assert result["initialActionableSecondaryEventCount"] == 2
    assert result["attemptedEventCount"] == 2
    assert result["unattemptedActionableEventCount"] == 0
    assert result["finalIncompleteEventCount"] == 0
    assert result["finalConflictEventCount"] == 0
    assert result["status"] == "bounded_sweep_completed"
    assert result["policy"]["automaticCanonicalization"] is False


def test_sweep_rejects_changed_instrument_identity_between_batches(tmp_path: Path) -> None:
    database = _database(tmp_path)
    first = _instrument(database, "AAA")
    second = _instrument(database, "BBB")
    effective = "2026-08-15T00:00:00+00:00"
    _seed_yahoo_dividend(database, first, effective_at=effective)
    _seed_yahoo_dividend(database, second, effective_at=effective)
    provider = FakeAlphaVantageProvider({
        "AAA": [_alpha_dividend("AAA", effective, 0.25)],
        "BBB": [_alpha_dividend("BBB", effective, 0.25)],
    })

    def change_second_listing(event: dict[str, object]) -> None:
        if event["symbol"] == "AAA" and event["status"] == "persisted":
            with database.connect() as connection:
                connection.execute(
                    "UPDATE instruments SET currency = 'EUR' WHERE id = ?", (second,),
                )

    result = VerifiedCorporateActionSecondaryBackfillService(
        database=database, history_provider=provider,
        clock=lambda: VERIFIED_AT, progress_callback=change_second_listing,
    ).run_sweep(as_of=AS_OF, limit=1, max_batches=2)

    assert [call[0] for call in provider.calls] == ["AAA"]
    assert result["failedInstrumentCount"] == 1
    assert result["status"] == "completed_with_failures"
    assert result["batches"][1]["failures"][0]["error"] == "frozen_instrument_identity_changed"
    assert result["finalIncompleteEventCount"] == 1


def test_sweep_reports_bounded_unattempted_actionable_work(tmp_path: Path) -> None:
    database = _database(tmp_path)
    effective = "2026-08-15T00:00:00+00:00"
    for symbol in ("AAA", "BBB"):
        _seed_yahoo_dividend(database, _instrument(database, symbol), effective_at=effective)
    provider = FakeAlphaVantageProvider({
        "AAA": [_alpha_dividend("AAA", effective, 0.25)],
        "BBB": [_alpha_dividend("BBB", effective, 0.25)],
    })
    result = VerifiedCorporateActionSecondaryBackfillService(
        database=database, history_provider=provider, clock=lambda: VERIFIED_AT,
    ).run_sweep(as_of=AS_OF, limit=1, max_batches=1)

    assert result["status"] == "bounded_sweep_partial"
    assert result["initialActionableSecondaryEventCount"] == 2
    assert result["attemptedEventCount"] == 1
    assert result["unattemptedActionableEventCount"] == 1
    assert result["completeActionableSelection"] is False


def test_sweep_cli_returns_nonzero_for_unattempted_events(monkeypatch) -> None:
    import sys
    from scripts import backfill_verified_secondary_corporate_actions as cli

    monkeypatch.setattr(sys, "argv", ["backfill_verified_secondary_corporate_actions", "--sweep"])
    monkeypatch.setattr(cli, "run_sweep", lambda **kwargs: {
        "status": "bounded_sweep_partial",
        "unattemptedActionableEventCount": 1,
        "failedInstrumentCount": 0,
    })
    assert cli.main() == 3


def test_sweep_cli_returns_nonzero_for_failed_identity(monkeypatch) -> None:
    import sys
    from scripts import backfill_verified_secondary_corporate_actions as cli

    monkeypatch.setattr(sys, "argv", ["backfill_verified_secondary_corporate_actions", "--sweep"])
    monkeypatch.setattr(cli, "run_sweep", lambda **kwargs: {
        "status": "completed_with_failures",
        "unattemptedActionableEventCount": 0,
        "failedInstrumentCount": 1,
    })
    assert cli.main() == 3

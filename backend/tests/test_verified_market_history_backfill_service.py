from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.verified_market_history_backfill_service import VerifiedMarketHistoryBackfillService


class FakeHistoryProvider:
    def __init__(self, responses: dict[str, list[dict[str, object]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get_history(self, symbol: str, from_date: str | None = None, to_date: str | None = None) -> list[dict[str, object]]:
        self.calls.append((symbol, from_date, to_date))
        return list(self.responses.get(symbol, []))


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _insert(repository: InstrumentRepository, symbol: str) -> int:
    return repository.upsert({"symbol": symbol, "companyName": symbol, "country": "United States", "regionKey": "america", "exchangeShortName": "NASDAQ", "instrumentType": "common_stock"})


def _history(start: datetime, *, span_days: int, step_days: int = 5) -> list[dict[str, object]]:
    rows = [{"timestamp": (start + timedelta(days=day)).isoformat(), "sourceProvider": "yahoo", "close": 100.0 + day / 100} for day in range(0, span_days + 1, step_days)]
    final_timestamp = (start + timedelta(days=span_days)).isoformat()
    if not rows or rows[-1]["timestamp"] != final_timestamp:
        rows.append({"timestamp": final_timestamp, "sourceProvider": "yahoo", "close": 100.0 + span_days / 100})
    return rows


def test_verified_backfill_only_claims_criterion_after_persisted_current_365_day_history(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert(InstrumentRepository(database=database), "AAA")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider({"AAA": _history(start, span_days=365)})

    report = VerifiedMarketHistoryBackfillService(database=database, history_provider=provider, today_provider=lambda: date(2026, 1, 2)).run(limit=10)

    assert report.blockers_before == 1
    assert report.blockers_after == 0
    assert report.current_blockers_before == 1
    assert report.current_blockers_after == 0
    assert report.eligible_instrument_count == 1
    assert report.net_blockers_resolved == 1
    assert report.net_current_blockers_resolved == 1
    assert report.history_ready is True
    assert provider.calls == [("AAA", "2024-11-28", "2026-01-02")]

    verification = report.to_api_dict()["verification"]
    assert verification["deepHistoryCriterionSatisfied"] is True
    assert verification["eligibleInstrumentCount"] == 1
    assert verification["nonEmptyEligibleUniverseRequired"] is True
    assert verification["currentDepthRequired"] is True
    assert verification["currentBlockersAfter"] == 0
    assert verification["minimumHistoryDays"] == 365
    assert verification["maximumSourceGapDays"] == 7
    assert verification["providerStitchingAllowed"] is False
    assert report.to_api_dict()["policy"]["productionEvidenceClaimed"] is False


def test_empty_eligible_universe_cannot_vacuously_satisfy_history_readiness(tmp_path: Path) -> None:
    database = _database(tmp_path)
    provider = FakeHistoryProvider({})

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=10)

    assert report.blockers_before == 0
    assert report.blockers_after == 0
    assert report.current_blockers_before == 0
    assert report.current_blockers_after == 0
    assert report.eligible_instrument_count == 0
    assert report.history_ready is False
    assert provider.calls == []
    payload = report.to_api_dict()
    assert payload["status"] == "history_criteria_still_blocked"
    assert payload["verification"]["eligibleInstrumentCount"] == 0
    assert payload["verification"]["nonEmptyEligibleUniverseRequired"] is True
    assert payload["verification"]["deepHistoryCriterionSatisfied"] is False
    assert payload["policy"]["productionEvidenceClaimed"] is False


def test_deep_but_stale_persisted_history_cannot_claim_verified_readiness(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _insert(InstrumentRepository(database=database), "AAA")
    stale_start = datetime(2024, 1, 1, 21, 0, tzinfo=timezone.utc)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=_history(stale_start, span_days=365),
        source_provider="yahoo_finance",
        retrieved_at=stale_start + timedelta(days=366),
    )

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=FakeHistoryProvider({}),
        today_provider=lambda: date(2026, 1, 15),
    ).run(limit=10)

    assert report.blockers_before == 0
    assert report.blockers_after == 0
    assert report.current_blockers_before == 1
    assert report.current_blockers_after == 1
    assert report.history_ready is False
    payload = report.to_api_dict()
    assert payload["status"] == "history_criteria_still_blocked"
    assert payload["verification"]["deepHistoryCriterionSatisfied"] is False
    assert payload["verification"]["currentDepthRequired"] is True


def test_persisted_rows_do_not_hide_an_insufficient_span_blocker(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert(InstrumentRepository(database=database), "AAA")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    report = VerifiedMarketHistoryBackfillService(database=database, history_provider=FakeHistoryProvider({"AAA": _history(start, span_days=100)}), today_provider=lambda: date(2026, 1, 2)).run(limit=10)
    assert report.backfill.persisted_instrument_count == 1
    assert report.blockers_after == 1
    assert report.current_blockers_after == 1
    assert report.history_ready is False


def test_partial_batch_reports_remaining_unprocessed_blockers(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, "AAA")
    _insert(instruments, "BBB")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider({"AAA": _history(start, span_days=365), "BBB": _history(start, span_days=365)})
    report = VerifiedMarketHistoryBackfillService(database=database, history_provider=provider, today_provider=lambda: date(2026, 1, 2)).run(limit=1)
    assert report.blockers_before == 2
    assert report.blockers_after == 1
    assert report.current_blockers_after == 1
    assert report.history_ready is False
    assert [call[0] for call in provider.calls] == ["AAA"]


def test_no_history_remains_a_blocker_and_never_claims_operational_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert(InstrumentRepository(database=database), "AAA")
    report = VerifiedMarketHistoryBackfillService(database=database, history_provider=FakeHistoryProvider({"AAA": []}), today_provider=lambda: date(2026, 1, 2)).run(limit=10)
    assert report.backfill.no_history_count == 1
    assert report.blockers_after == 1
    assert report.current_blockers_after == 1
    assert report.history_ready is False
    assert report.to_api_dict()["policy"]["productionEvidenceClaimed"] is False

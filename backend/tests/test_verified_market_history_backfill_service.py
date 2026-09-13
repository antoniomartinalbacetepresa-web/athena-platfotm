from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.verified_market_history_backfill_service import (
    VerifiedMarketHistoryBackfillService,
)


class FakeHistoryProvider:
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


def _insert(repository: InstrumentRepository, symbol: str) -> int:
    return repository.upsert(
        {
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
        }
    )


def _history(start: datetime, *, span_days: int, step_days: int = 5) -> list[dict[str, object]]:
    rows = [
        {
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "sourceProvider": "yahoo",
            "close": 100.0 + day / 100,
        }
        for day in range(0, span_days + 1, step_days)
    ]
    final_timestamp = (start + timedelta(days=span_days)).isoformat()
    if not rows or rows[-1]["timestamp"] != final_timestamp:
        rows.append(
            {
                "timestamp": final_timestamp,
                "sourceProvider": "yahoo",
                "close": 100.0 + span_days / 100,
            }
        )
    return rows


def test_verified_backfill_only_claims_criterion_after_persisted_365_day_history(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, "AAA")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider({"AAA": _history(start, span_days=365)})

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=10)

    assert report.blockers_before == 1
    assert report.blockers_after == 0
    assert report.net_blockers_resolved == 1
    assert report.history_ready is True
    assert provider.calls == [("AAA", "2024-11-28", "2026-01-02")]

    payload = report.to_api_dict()
    assert payload["status"] == "history_criteria_satisfied"
    assert payload["verification"] == {
        "blockersBefore": 1,
        "blockersAfter": 0,
        "netBlockersResolved": 1,
        "deepHistoryCriterionSatisfied": True,
        "minimumHistoryDays": 365,
        "maximumSourceGapDays": 7,
        "providerStitchingAllowed": False,
    }
    assert payload["policy"] == {
        "productionEvidenceClaimed": False,
        "automaticReadinessPromotion": False,
        "automaticTrading": False,
        "humanReviewBypassed": False,
    }


def test_persisted_rows_do_not_hide_an_insufficient_span_blocker(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, "AAA")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider({"AAA": _history(start, span_days=100)})

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=10)

    assert report.backfill.persisted_instrument_count == 1
    assert report.backfill.observations_inserted > 0
    assert report.blockers_before == 1
    assert report.blockers_after == 1
    assert report.net_blockers_resolved == 0
    assert report.history_ready is False
    payload = report.to_api_dict()
    assert payload["status"] == "history_criteria_still_blocked"
    assert payload["verification"]["deepHistoryCriterionSatisfied"] is False
    assert payload["policy"]["productionEvidenceClaimed"] is False


def test_partial_batch_reports_remaining_unprocessed_blockers(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, "AAA")
    _insert(instruments, "BBB")
    start = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)
    provider = FakeHistoryProvider(
        {
            "AAA": _history(start, span_days=365),
            "BBB": _history(start, span_days=365),
        }
    )

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=1)

    assert report.blockers_before == 2
    assert report.blockers_after == 1
    assert report.net_blockers_resolved == 1
    assert report.history_ready is False
    assert [call[0] for call in provider.calls] == ["AAA"]


def test_no_history_remains_a_blocker_and_never_claims_operational_evidence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    _insert(instruments, "AAA")
    provider = FakeHistoryProvider({"AAA": []})

    report = VerifiedMarketHistoryBackfillService(
        database=database,
        history_provider=provider,
        today_provider=lambda: date(2026, 1, 2),
    ).run(limit=10)

    assert report.backfill.no_history_count == 1
    assert report.blockers_after == 1
    assert report.history_ready is False
    assert report.to_api_dict()["policy"]["productionEvidenceClaimed"] is False

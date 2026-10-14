from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_history_backfill_plan_service import (
    MarketHistoryBackfillPlanService,
)


AS_OF = datetime(2026, 9, 13, 19, 45, tzinfo=timezone.utc)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(repository: InstrumentRepository, symbol: str) -> int:
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


def _continuous_history(base: datetime, *, days: int = 365) -> list[dict[str, object]]:
    return [
        {
            "timestamp": (base + timedelta(days=day)).isoformat(),
            "close": 100.0 + day / 100,
        }
        for day in range(0, days + 1, 5)
    ]


def test_plan_turns_only_unresolved_gaps_into_400_day_yahoo_requests(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    no_history = _instrument(instruments, "AAA")
    short_history = _instrument(instruments, "BBB")
    deep_history = _instrument(instruments, "CCC")
    observations = MarketObservationRepository(database=database)
    base = datetime(2025, 1, 1, 21, 0, tzinfo=timezone.utc)

    observations.save_many(
        instrument_id=short_history,
        observations=[
            {"timestamp": base.isoformat(), "close": 100.0},
            {"timestamp": (base + timedelta(days=100)).isoformat(), "close": 101.0},
        ],
        source_provider="source_a",
        retrieved_at=base + timedelta(days=101),
    )
    observations.save_many(
        instrument_id=deep_history,
        observations=_continuous_history(base),
        source_provider="source_b",
        retrieved_at=base + timedelta(days=366),
    )

    plan = MarketHistoryBackfillPlanService(database=database).get_plan(as_of=AS_OF)

    assert plan.total_blocking_count == 2
    assert [request.instrument_id for request in plan.requests] == [no_history, short_history]
    assert [request.symbol for request in plan.requests] == ["AAA", "BBB"]
    assert {request.reason for request in plan.requests} == {
        "no_observations",
        "insufficient_span",
    }
    assert {request.source_provider for request in plan.requests} == {"yahoo"}
    assert {request.requested_history_days for request in plan.requests} == {400}
    assert {request.to_date for request in plan.requests} == {"2026-09-13"}
    assert {request.from_date for request in plan.requests} == {"2025-08-09"}

    payload = plan.to_api_dict()
    assert payload["status"] == "backfill_plan_only"
    assert payload["selectedCount"] == 2
    assert payload["hasMore"] is False
    assert payload["minimumHistoryDays"] == 365
    assert payload["requestedHistoryDays"] == 400
    assert payload["policy"] == {
        "primarySourceProvider": "yahoo",
        "providerStitchingAllowed": False,
        "replaceExistingObservations": False,
        "productionEvidenceClaimed": False,
        "automaticReadinessPromotion": False,
    }
    assert all(item["providerStitchingAllowed"] is False for item in payload["requests"])
    assert all(item["replaceExistingObservations"] is False for item in payload["requests"])


def test_plan_preserves_gap_pagination_and_reports_remaining_work(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    for symbol in ("AAA", "BBB", "CCC"):
        _instrument(instruments, symbol)

    plan = MarketHistoryBackfillPlanService(database=database).get_plan(
        as_of=AS_OF,
        limit=1,
        offset=1,
    )

    assert plan.total_blocking_count == 3
    assert [request.symbol for request in plan.requests] == ["BBB"]
    payload = plan.to_api_dict()
    assert payload["selectedCount"] == 1
    assert payload["hasMore"] is True
    assert payload["offset"] == 1


def test_plan_refuses_weaker_than_required_history_and_naive_cutoffs(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with pytest.raises(ValueError, match="inferior a 365"):
        MarketHistoryBackfillPlanService(database=database, minimum_history_days=364)
    with pytest.raises(ValueError, match="safety_margin_days"):
        MarketHistoryBackfillPlanService(database=database, safety_margin_days=-1)
    with pytest.raises(ValueError, match="maximum_source_gap_days"):
        MarketHistoryBackfillPlanService(database=database, maximum_source_gap_days=0)

    service = MarketHistoryBackfillPlanService(database=database)
    with pytest.raises(ValueError, match="zona horaria"):
        service.get_plan(as_of=datetime(2026, 9, 13, 19, 45))

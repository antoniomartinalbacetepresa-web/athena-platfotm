"""HTTP contract for the read-only Market backfill planner (synthetic fixtures only)."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import market as market_api
from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.market_history_backfill_plan_service import MarketHistoryBackfillPlanService


AS_OF = datetime(2026, 9, 13, 19, 45, tzinfo=timezone.utc)


def test_market_backfill_plan_api_paginates_without_promoting_synthetic_data(
    tmp_path, monkeypatch,
) -> None:
    database = AthenaDatabase(tmp_path / "synthetic-market.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    for symbol in ("AAA", "BBB", "CCC"):
        instruments.upsert({
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NASDAQ",
            "instrumentType": "common_stock",
        })

    monkeypatch.setattr(
        market_api,
        "MarketHistoryBackfillPlanService",
        lambda: MarketHistoryBackfillPlanService(database=database),
    )
    app = FastAPI()
    app.include_router(market_api.router)
    client = TestClient(app)
    params = {"asOf": AS_OF.isoformat(), "limit": 1}
    collected = []
    for offset in range(3):
        response = client.get(
            "/api/v1/market/history/backfill-plan",
            params={**params, "offset": offset},
        )
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        assert payload["status"] == "backfill_plan_only"
        assert payload["totalBlockingCount"] == 3
        assert payload["selectedCount"] == 1
        assert payload["remainingCount"] == 2 - offset
        assert payload["hasMore"] is (offset < 2)
        assert payload["nextOffset"] == (offset + 1 if offset < 2 else None)
        assert payload["policy"]["productionEvidenceClaimed"] is False
        assert payload["policy"]["automaticReadinessPromotion"] is False
        assert payload["requests"][0]["sourceProvider"] == "yahoo"
        collected.append(payload["requests"][0]["symbol"])

    assert collected == ["AAA", "BBB", "CCC"]
    repeat = client.get(
        "/api/v1/market/history/backfill-plan", params={**params, "offset": 0}
    )
    assert repeat.status_code == 200
    assert repeat.json()["data"]["requests"][0]["symbol"] == "AAA"


def test_market_backfill_plan_api_rejects_invalid_pit_and_pagination() -> None:
    app = FastAPI()
    app.include_router(market_api.router)
    client = TestClient(app)
    url = "/api/v1/market/history/backfill-plan"
    for params, expected_status in (
        ({"asOf": "2026-09-13T19:45:00"}, 400),
        ({"asOf": "2999-01-01T00:00:00+00:00"}, 400),
        ({"asOf": AS_OF.isoformat(), "limit": 0}, 422),
        ({"asOf": AS_OF.isoformat(), "offset": -1}, 422),
    ):
        response = client.get(url, params=params)
        assert response.status_code == expected_status, response.text


def test_market_backfill_plan_api_empty_and_out_of_range_pages(
    tmp_path, monkeypatch,
) -> None:
    """Empty or exhausted pages must not fabricate missing market history."""
    database = AthenaDatabase(tmp_path / "synthetic-empty-market.db")
    database.initialize()
    monkeypatch.setattr(
        market_api,
        "MarketHistoryBackfillPlanService",
        lambda: MarketHistoryBackfillPlanService(database=database),
    )
    app = FastAPI()
    app.include_router(market_api.router)
    client = TestClient(app)
    url = "/api/v1/market/history/backfill-plan"
    params = {"asOf": AS_OF.isoformat(), "limit": 1}

    empty = client.get(url, params=params)
    assert empty.status_code == 200, empty.text
    payload = empty.json()["data"]
    assert payload["totalBlockingCount"] == 0
    assert payload["selectedCount"] == 0
    assert payload["requests"] == []
    assert payload["remainingCount"] == 0
    assert payload["hasMore"] is False
    assert payload["nextOffset"] is None
    assert payload["policy"]["productionEvidenceClaimed"] is False

    InstrumentRepository(database=database).upsert({
        "symbol": "AAA",
        "companyName": "AAA",
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "NASDAQ",
        "instrumentType": "common_stock",
    })
    exhausted = client.get(url, params={**params, "offset": 10})
    assert exhausted.status_code == 200, exhausted.text
    payload = exhausted.json()["data"]
    assert payload["totalBlockingCount"] == 1
    assert payload["selectedCount"] == 0
    assert payload["requests"] == []
    assert payload["remainingCount"] == 0
    assert payload["hasMore"] is False
    assert payload["nextOffset"] is None
    assert payload["policy"]["automaticReadinessPromotion"] is False

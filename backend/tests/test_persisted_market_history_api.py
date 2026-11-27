"""Synthetic persistence -> API regressions; no provider data or licence claims."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.api import market
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.persisted_market_history_service import PersistedMarketHistoryService


OBSERVED = datetime(2026, 11, 23, 21, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    database = AthenaDatabase(tmp_path / "synthetic-persisted-api.db")
    database.initialize()
    instrument_id = InstrumentRepository(database).upsert({
        "symbol": "SYNTH", "companyName": "Synthetic API fixture",
        "exchangeShortName": "TEST", "currency": "USD",
        "instrumentType": "common_stock",
    })
    repository = MarketObservationRepository(database)
    observations = [{"timestamp": OBSERVED + timedelta(days=day),
                     "open": 99, "high": 103, "low": 98, "close": 101 + day,
                     "volume": 200 + day} for day in range(2)]
    saved_at = RETRIEVED + timedelta(days=1)
    assert repository.save_many(instrument_id=instrument_id, observations=observations,
                                source_provider="synthetic_fixture", retrieved_at=saved_at).inserted == 2
    # Replay is idempotent and cannot replace the first retrieval/price.
    assert repository.save_many(instrument_id=instrument_id, observations=observations,
                                source_provider="synthetic_fixture", retrieved_at=saved_at).unchanged == 2
    monkeypatch.setattr(market, "PersistedMarketHistoryService",
                        lambda: PersistedMarketHistoryService(database))
    monkeypatch.setattr(market.market_service, "get_history",
                        lambda **_: pytest.fail("persisted reads must not fetch a provider"))
    params = {"instrumentId": instrument_id, "sourceProvider": "synthetic_fixture",
              "observedFrom": OBSERVED.isoformat(),
              "observedTo": (OBSERVED + timedelta(days=1)).isoformat(),
              "asOf": saved_at.isoformat()}
    return database, params


def test_restarted_repository_is_exposed_with_stable_provenance_and_no_authority(stored):
    _, params = stored
    first = TestClient(app).get("/api/v1/market/history/persisted", params=params)
    assert first.status_code == 200
    body = first.json()
    assert [row["close"] for row in body["data"]] == [101, 102]
    assert [row["volume"] for row in body["data"]] == [200, 201]
    assert all(row["instrumentId"] == params["instrumentId"] for row in body["data"])
    assert all(row["availableAt"] == row["retrievedAt"] == params["asOf"] for row in body["data"])
    assert all(row["sourceTimestamp"] is None for row in body["data"])
    provenance = body["provenance"]
    assert provenance["historyStatus"] == "persisted_unverified"
    for flag in ("licenceVerified", "historicalPointInTimeEligible",
                 "productionCoverageClaimed", "orderExecutionAllowed", "truncated"):
        assert provenance[flag] is False
    assert TestClient(app).get("/api/v1/market/history/persisted", params=params).json() == body


def test_cutoff_is_exact_to_microsecond_and_never_backdates_retrieval(stored):
    _, params = stored
    cutoff = datetime.fromisoformat(params["asOf"]) - timedelta(microseconds=1)
    response = TestClient(app).get("/api/v1/market/history/persisted",
                                   params=params | {"asOf": cutoff.isoformat()})
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["provenance"]["historyStatus"] == "empty"


def test_limit_returns_latest_rows_with_explicit_truncation(stored):
    _, params = stored
    response = TestClient(app).get("/api/v1/market/history/persisted", params=params | {"limit": 1})
    assert response.status_code == 200
    assert [row["close"] for row in response.json()["data"]] == [102]
    assert response.json()["provenance"]["truncated"] is True


@pytest.mark.parametrize("field,value", [
    ("asOf", "2026-11-25T10:00:00"), ("sourceProvider", "twelve%5Fdata"),
    ("observedFrom", "2020-01-01T00:00:00Z"),
    ("observedTo", "2026-12-01T00:00:00Z"),
])
def test_invalid_or_unauthorized_selection_is_rejected(stored, field, value):
    _, params = stored
    response = TestClient(app).get("/api/v1/market/history/persisted", params=params | {field: value})
    assert response.status_code == 400


def test_source_selection_never_falls_back(stored):
    _, params = stored
    response = TestClient(app).get("/api/v1/market/history/persisted",
                                   params=params | {"sourceProvider": "synthetic_other"})
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_corrupt_imported_ohlc_cannot_be_exposed_as_a_valid_candle(stored):
    database, params = stored
    with database.connect() as connection:
        connection.execute("UPDATE market_observations SET high = 1")
    response = TestClient(app).get("/api/v1/market/history/persisted", params=params)
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_unknown_listing_is_not_an_empty_history(stored):
    _, params = stored
    response = TestClient(app).get("/api/v1/market/history/persisted", params=params | {"instrumentId": 999})
    assert response.status_code == 404


def test_storage_outage_is_sanitized_not_empty(stored, monkeypatch):
    _, params = stored
    def fail(**_):
        raise RuntimeError("private database path and synthetic-secret")
    monkeypatch.setattr(market, "PersistedMarketHistoryService", lambda: type("Unavailable", (), {"get_history": staticmethod(fail)})())
    response = TestClient(app).get("/api/v1/market/history/persisted", params=params)
    assert response.status_code == 503
    assert "synthetic-secret" not in response.text

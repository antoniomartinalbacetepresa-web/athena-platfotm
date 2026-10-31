from fastapi.testclient import TestClient

from app.api import readiness as readiness_api
from app.main import app


client = TestClient(app)


def test_readiness_endpoint_returns_diagnostics(monkeypatch) -> None:
    expected = {
        "status": "athena_readiness_diagnostics",
        "asOf": "2026-09-10T10:00:00+00:00",
        "operationalReadiness": {
            "completionPercent": 40.0,
            "ready": False,
            "blockers": ["market_history_missing"],
        },
        "automaticActivation": False,
    }

    monkeypatch.setattr(
        readiness_api,
        "build_readiness_report",
        lambda: expected,
    )

    response = client.get("/api/v1/readiness")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["automaticActivation"] is False


def test_readiness_endpoint_is_get_only(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness_api,
        "build_readiness_report",
        lambda: {
            "status": "athena_readiness_diagnostics",
            "automaticActivation": False,
        },
    )

    response = client.post("/api/v1/readiness")

    assert response.status_code == 405


def test_market_history_gap_api_paginates_real_pit_blockers(tmp_path, monkeypatch) -> None:
    from app.database.athena_database import AthenaDatabase
    from app.repositories.instrument_repository import InstrumentRepository
    from app.services.market_history_gap_service import MarketHistoryGapService

    database = AthenaDatabase(tmp_path / "market-history.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    for symbol in ("AAA", "BBB", "CCC"):
        instruments.upsert({
            "symbol": symbol,
            "companyName": symbol,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": symbol,
            "instrumentType": "common_stock",
        })
    monkeypatch.setattr(
        readiness_api,
        "MarketHistoryGapService",
        lambda: MarketHistoryGapService(database=database),
    )

    response = client.get(
        "/api/v1/readiness/market-history/gaps",
        params={
            "asOf": "2026-09-01T21:00:00+00:00",
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "diagnostic_only"
    assert data["pointInTimeCutoffApplied"] is True
    assert data["asOf"] == "2026-09-01T21:00:00+00:00"
    assert data["totalBlockingCount"] == 3
    assert data["blockingByReason"]["no_observations"] == 3
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert [item["symbol"] for item in data["items"]] == ["BBB"]
    assert data["productionEvidenceClaimed"] is False


def test_market_history_gap_api_rejects_naive_cutoffs_and_invalid_pagination(
    monkeypatch,
) -> None:
    for params in (
        {"asOf": "2026-09-01T21:00:00"},
        {"limit": 0},
        {"limit": 1001},
        {"offset": -1},
    ):
        response = client.get(
            "/api/v1/readiness/market-history/gaps", params=params
        )
        assert response.status_code == 422

    assert client.post("/api/v1/readiness/market-history/gaps").status_code == 405


def test_market_history_gap_api_fails_closed_without_leaking_internal_errors(
    monkeypatch,
) -> None:
    class FailingGapService:
        def get_report(self, **kwargs):
            raise RuntimeError("API_KEY=do_not_leak")

    monkeypatch.setattr(
        readiness_api, "MarketHistoryGapService", FailingGapService
    )
    response = client.get("/api/v1/readiness/market-history/gaps")
    assert response.status_code == 503
    assert "API_KEY" not in response.text
    assert "diagnóstico PIT" in response.json()["detail"]


def test_market_history_coverage_api_measures_persisted_pit_and_matches_gap_counts(
    tmp_path, monkeypatch,
) -> None:
    from datetime import datetime, timezone

    from app.database.athena_database import AthenaDatabase
    from app.repositories.instrument_repository import InstrumentRepository
    from app.repositories.market_observation_repository import MarketObservationRepository
    from app.services.market_history_gap_service import MarketHistoryGapService
    from app.services.market_observation_coverage_service import (
        MarketObservationCoverageService,
    )

    database = AthenaDatabase(tmp_path / "pit-coverage.db")
    database.initialize()
    instruments = InstrumentRepository(database=database)
    known_id = instruments.upsert({
        "symbol": "KNOWN",
        "companyName": "Known",
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "KNOWN",
        "instrumentType": "common_stock",
    })
    late_id = instruments.upsert({
        "symbol": "LATE",
        "companyName": "Late",
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "LATE",
        "instrumentType": "common_stock",
    })
    observations = MarketObservationRepository(database=database)
    observed_at = datetime(2026, 8, 30, 21, tzinfo=timezone.utc)
    observations.save_many(
        instrument_id=known_id,
        observations=[{"timestamp": observed_at.isoformat(), "close": 100.0}],
        source_provider="yahoo",
        retrieved_at=datetime(2026, 8, 31, 21, tzinfo=timezone.utc),
    )
    observations.save_many(
        instrument_id=late_id,
        observations=[{"timestamp": observed_at.isoformat(), "close": 90.0}],
        source_provider="yahoo",
        retrieved_at=datetime(2026, 9, 2, 21, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        readiness_api, "MarketObservationCoverageService",
        lambda: MarketObservationCoverageService(database=database),
    )
    monkeypatch.setattr(
        readiness_api, "MarketHistoryGapService",
        lambda: MarketHistoryGapService(database=database),
    )

    cutoff = "2026-09-01T21:00:00+00:00"
    coverage_response = client.get(
        "/api/v1/readiness/market-history/coverage",
        params={"asOf": cutoff},
    )
    gap_response = client.get(
        "/api/v1/readiness/market-history/gaps",
        params={"asOf": cutoff},
    )
    assert coverage_response.status_code == 200
    assert gap_response.status_code == 200
    coverage = coverage_response.json()
    gaps = gap_response.json()
    assert coverage["status"] == "diagnostic_only"
    assert coverage["asOf"] == gaps["asOf"] == cutoff
    assert coverage["pointInTimeCutoffApplied"] is True
    assert coverage["productionCoverageClaimed"] is False
    assert coverage["historyEligibleInstrumentCount"] == 2
    assert coverage["coveredInstrumentCount"] == 1
    assert coverage["observationCount"] == 1
    assert coverage["bySource"]["yahoo"]["observationCount"] == 1
    assert coverage["currentDeepHistoryInstrumentCount"] == 0
    assert coverage["currentHistoryDepthReady"] is False
    assert gaps["totalBlockingCount"] == (
        coverage["historyEligibleInstrumentCount"]
        - coverage["currentDeepHistoryInstrumentCount"]
    )
    assert gaps["blockingByReason"]["no_observations"] == 1
    assert gaps["blockingByReason"]["insufficient_span"] == 1


def test_market_history_coverage_api_rejects_naive_cutoff_and_writes() -> None:
    response = client.get(
        "/api/v1/readiness/market-history/coverage",
        params={"asOf": "2026-09-01T21:00:00"},
    )
    assert response.status_code == 422
    assert client.post("/api/v1/readiness/market-history/coverage").status_code == 405


def test_market_history_coverage_api_fails_closed_without_leaking_secrets(
    monkeypatch,
) -> None:
    class FailingCoverageService:
        def get_report(self, **kwargs):
            raise RuntimeError("API_KEY=never_disclose")

    monkeypatch.setattr(
        readiness_api, "MarketObservationCoverageService", FailingCoverageService
    )
    response = client.get("/api/v1/readiness/market-history/coverage")
    assert response.status_code == 503
    assert "API_KEY" not in response.text
    assert "cobertura histórica PIT" in response.json()["detail"]

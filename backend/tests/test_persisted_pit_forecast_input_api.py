"""Synthetic integration regressions; fixtures are not production PIT evidence."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api import recommendation_persisted_forecast_inputs as persisted_api
from app.api import recommendation_research_forecast_evaluation as evaluation_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.repositories.recommendation_macro_pit_observation_repository import RecommendationMacroPitObservationRepository
from app.repositories.recommendation_research_evaluation_specification_repository import RecommendationResearchEvaluationSpecificationRepository
from app.services.persisted_forecast_input_manifest_service import PersistedForecastInputManifestService
from app.services.persisted_macro_forecast_input_service import PersistedMacroForecastInputService
from app.services.persisted_market_forecast_input_service import PersistedMarketForecastInputService
from test_recommendation_research_forecast_evaluation import _cycle_record, CYCLE_HASH


def test_api_seals_and_reverifies_persisted_market_v3(monkeypatch, tmp_path):
    database = AthenaDatabase(tmp_path / "persisted-market-api.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
        }
    )
    observed_at = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    retrieved_at = observed_at + timedelta(minutes=1)
    cutoff = retrieved_at + timedelta(seconds=1)
    forecast_at = cutoff + timedelta(seconds=1)
    period_start = forecast_at + timedelta(days=1)
    market_repository = MarketObservationRepository(database=database)
    market_repository.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": observed_at.isoformat(), "close": 100.0, "volume": 1000}],
        source_provider="yahoo_finance",
        retrieved_at=retrieved_at,
    )

    cycle = _cycle_record()
    cycle["package"]["cycle"]["asOf"] = cutoff.isoformat()

    class Cycles:
        def get_by_hash(self, *, cycle_hash):
            assert cycle_hash == CYCLE_HASH
            return cycle

    market_service = PersistedMarketForecastInputService(market_repository)
    macro_service = PersistedMacroForecastInputService(
        RecommendationMacroPitObservationRepository(database),
        market_service=market_service,
    )
    manifest_service = PersistedForecastInputManifestService(
        macro_service=macro_service,
        market_service=market_service,
    )
    specification_repository = RecommendationResearchEvaluationSpecificationRepository(
        database,
        now_provider=lambda: forecast_at,
    )
    cycles = Cycles()
    monkeypatch.setattr(persisted_api, "cycle_repository", cycles)
    monkeypatch.setattr(persisted_api, "manifest_service", manifest_service)
    monkeypatch.setattr(evaluation_api, "cycle_repository", cycles)
    monkeypatch.setattr(evaluation_api, "specification_repository", specification_repository)
    monkeypatch.setattr(evaluation_api, "persisted_macro_input_service", macro_service)

    response = TestClient(app).post(
        f"/api/v1/recommendations/professional-research/research-cycle/{CYCLE_HASH}/persisted-pit-evaluation-specification",
        json={
            "specificationId": "market-v3-integration",
            "horizonSeconds": 86400,
            "expectedTotalReturn": 0.01,
            "availableAt": forecast_at.isoformat(),
            "periodStart": period_start.isoformat(),
            "source": "athena-test",
            "sourceRef": "urn:test:forecast-output",
            "method": "synthetic-regression-only",
            "marketObservations": [{
                "instrumentId": instrument_id,
                "sourceProvider": "yahoo_finance",
                "observedAt": observed_at.isoformat(),
            }],
        },
    )
    assert response.status_code == 200, response.text
    artifact = response.json()["data"]
    assert artifact["artifactVersion"] == "research-evaluation-specification-v3"
    assert artifact["productionEligible"] is False
    assert artifact["productionLearningEligible"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert artifact["inputEvidence"][0]["sourceRef"].startswith(market_service.PREFIX)

    specification_hash = artifact["specificationHash"]
    read = TestClient(app).get(
        f"/api/v1/recommendations/professional-research/evaluation-specification/{specification_hash}"
    )
    assert read.status_code == 200, read.text


def test_api_rejects_empty_persisted_manifest(monkeypatch):
    cycle = _cycle_record()
    cutoff = datetime.fromisoformat(cycle["package"]["cycle"]["asOf"])

    class Cycles:
        def get_by_hash(self, *, cycle_hash):
            return cycle

    monkeypatch.setattr(persisted_api, "cycle_repository", Cycles())
    response = TestClient(app).post(
        f"/api/v1/recommendations/professional-research/research-cycle/{CYCLE_HASH}/persisted-pit-evaluation-specification",
        json={
            "specificationId": "empty-v3",
            "horizonSeconds": 86400,
            "expectedTotalReturn": 0.01,
            "availableAt": (cutoff + timedelta(seconds=1)).isoformat(),
            "periodStart": (cutoff + timedelta(days=1)).isoformat(),
            "source": "athena-test",
            "sourceRef": "urn:test:forecast-output",
            "method": "synthetic-regression-only",
        },
    )
    assert response.status_code == 400
    assert "al menos un input PIT" in response.json()["detail"]

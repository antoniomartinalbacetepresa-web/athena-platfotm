"""Synthetic regressions only; these fixtures are not production forecast evidence."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.persisted_market_forecast_input_service import PersistedMarketForecastInputService


def _context(tmp_path):
    database = AthenaDatabase(tmp_path / "market-inputs.db")
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
    repository = MarketObservationRepository(database=database)
    observed = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
    retrieved = observed + timedelta(minutes=1)
    repository.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": observed.isoformat(), "close": 100.0, "volume": 1000}],
        source_provider="yahoo_finance",
        retrieved_at=retrieved,
    )
    return database, repository, instrument_id, observed, retrieved


def _selection(instrument_id, observed, provider="yahoo_finance"):
    return {"instrumentId": instrument_id, "sourceProvider": provider, "observedAt": observed.isoformat()}


def test_resolve_binds_exact_persisted_market_row(tmp_path):
    _, repository, instrument_id, observed, retrieved = _context(tmp_path)
    service = PersistedMarketForecastInputService(repository)
    result = service.resolve(
        selections=[_selection(instrument_id, observed)],
        knowledge_cutoff=retrieved + timedelta(seconds=1),
        forecast_available_at=retrieved + timedelta(seconds=2),
    )
    assert result[0]["source"] == "yahoo_finance"
    assert result[0]["sourceRef"].startswith(service.PREFIX)
    assert result[0]["availableAt"] == retrieved.isoformat()
    assert len(result[0]["contentHash"]) == 64


def test_resolve_rejects_row_persisted_after_cycle_cutoff(tmp_path):
    _, repository, instrument_id, observed, retrieved = _context(tmp_path)
    service = PersistedMarketForecastInputService(repository)
    with pytest.raises(ValueError, match="no existe de forma única"):
        service.resolve(
            selections=[_selection(instrument_id, observed)],
            knowledge_cutoff=retrieved - timedelta(seconds=1),
            forecast_available_at=retrieved + timedelta(seconds=2),
        )


def test_resolve_rejects_duplicate_selection(tmp_path):
    _, repository, instrument_id, observed, retrieved = _context(tmp_path)
    selection = _selection(instrument_id, observed)
    with pytest.raises(ValueError, match="duplicadas"):
        PersistedMarketForecastInputService(repository).resolve(
            selections=[selection, selection],
            knowledge_cutoff=retrieved + timedelta(seconds=1),
            forecast_available_at=retrieved + timedelta(seconds=2),
        )


def test_verify_detects_persisted_row_tampering(tmp_path):
    database, repository, instrument_id, observed, retrieved = _context(tmp_path)
    service = PersistedMarketForecastInputService(repository)
    cutoff = retrieved + timedelta(seconds=1)
    forecast_at = retrieved + timedelta(seconds=2)
    inputs = service.resolve(
        selections=[_selection(instrument_id, observed)],
        knowledge_cutoff=cutoff,
        forecast_available_at=forecast_at,
    )
    artifact = {
        "cycleAsOf": cutoff.isoformat(),
        "forecastEvidence": {"availableAt": forecast_at.isoformat()},
        "inputEvidence": inputs,
    }
    with database.connect() as connection:
        row = connection.execute("SELECT id FROM market_observations LIMIT 1").fetchone()
        connection.execute("UPDATE market_observations SET close = ? WHERE id = ?", (999.0, row["id"]))
    with pytest.raises(ValueError, match="no coincide"):
        service.verify_specification(artifact)


def test_verify_rejects_unresolvable_market_reference(tmp_path):
    _, repository, _, _, _ = _context(tmp_path)
    service = PersistedMarketForecastInputService(repository)
    artifact = {
        "cycleAsOf": datetime(2026, 1, 3, tzinfo=timezone.utc).isoformat(),
        "forecastEvidence": {"availableAt": datetime(2026, 1, 4, tzinfo=timezone.utc).isoformat()},
        "inputEvidence": [{
            "source": "yahoo_finance",
            "sourceRef": service.PREFIX + "not-base64-json",
            "availableAt": datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat(),
            "contentHash": "a" * 64,
        }],
    }
    with pytest.raises(ValueError, match="no es resoluble"):
        service.verify_specification(artifact)

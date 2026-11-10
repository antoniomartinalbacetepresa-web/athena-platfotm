"""PIT price provenance: retain source publication time without inventing it."""
from datetime import datetime, timedelta, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_pit_price_selection_service import select_pit_prices


def test_pit_price_exposes_only_validated_source_timestamp(tmp_path):
    database = AthenaDatabase(tmp_path / "pit-source.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "TEST", "companyName": "Test", "country": "United States",
        "regionKey": "america", "exchangeShortName": "TEST",
        "instrumentType": "common_stock",
    })
    observed = datetime(2025, 1, 2, 21, tzinfo=timezone.utc)
    retrieved = observed + timedelta(hours=1)
    MarketObservationRepository(database=database).save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": observed.isoformat(), "close": 101.0}],
        source_provider="yahoo", retrieved_at=retrieved,
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_observations SET source_timestamp = ? WHERE instrument_id = ?",
            ((observed + timedelta(minutes=5)).isoformat(), instrument_id),
        )
    params = dict(database=database, instrument_id=instrument_id,
                  at_or_after=observed, not_after=observed,
                  knowledge_cutoff=retrieved)
    rows = select_pit_prices(**params)
    assert len(rows) == 1
    assert rows[0]["source_timestamp"] == (observed + timedelta(minutes=5)).isoformat()
    assert rows[0]["source_provider"] == "yahoo"

    # Imported legacy evidence claiming publication after retrieval must fail closed.
    with database.connect() as connection:
        connection.execute(
            "UPDATE market_observations SET source_timestamp = ? WHERE instrument_id = ?",
            ((retrieved + timedelta(microseconds=1)).isoformat(), instrument_id),
        )
    assert select_pit_prices(**params) == ()

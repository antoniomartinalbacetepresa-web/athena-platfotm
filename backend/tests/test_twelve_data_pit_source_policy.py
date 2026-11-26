"""Synthetic regressions: uncertified previews never become PIT evidence."""
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_pit_price_selection_service import select_pit_prices


PROVIDERS = ["twelve_data", "Twelve-Data", "TWELVE DATA", "twelve%5Fdata",
             "twelve&#95;data", "twelve%255Fdata"]
OBSERVED = datetime(2026, 11, 23, 21, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 11, 26, 15, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    database = AthenaDatabase(tmp_path / "synthetic-source-policy.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "SYNTH", "companyName": "Synthetic provenance fixture",
        "exchangeShortName": "TEST", "instrumentType": "common_stock",
        "currency": "USD",
    })
    return database, instrument_id, MarketObservationRepository(database=database)


@pytest.mark.parametrize("provider", PROVIDERS[3:])
def test_encoded_preview_source_is_rejected_before_storage(store, provider):
    _, instrument_id, repository = store
    with pytest.raises(ValueError, match="Twelve Data"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[{"timestamp": OBSERVED, "close": 102}],
            source_provider=provider, retrieved_at=RETRIEVED,
        )
    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_row_source_policy_rejects_relabelled_preview_atomically(store, provider):
    _, instrument_id, repository = store
    with pytest.raises(ValueError, match="Twelve Data"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[
                {"timestamp": OBSERVED, "close": 100},
                {"timestamp": OBSERVED, "close": 102,
                 "sourceProvider": provider, "historicalPointInTimeEligible": True},
            ],
            source_provider="synthetic_fixture", retrieved_at=RETRIEVED,
        )
    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_legacy_preview_cannot_override_valid_synthetic_pit_price(store, provider):
    database, instrument_id, repository = store
    repository.save_many(
        instrument_id=instrument_id,
        observations=[{"timestamp": OBSERVED, "close": 100}],
        source_provider="synthetic_fixture", retrieved_at=RETRIEVED,
    )
    # Emulate an imported row that predates write-time checks. No real data.
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO market_observations
               (instrument_id, observed_at, close, source_provider, retrieved_at)
               VALUES (?, ?, ?, ?, ?)""",
            (instrument_id, OBSERVED.isoformat(), 999, provider, RETRIEVED.isoformat()),
        )
    assert [row["source_provider"] for row in repository.list_for_instrument(instrument_id)] == [
        "synthetic_fixture",
    ]
    prices = select_pit_prices(
        database, instrument_id=instrument_id, at_or_after=OBSERVED,
        not_after=OBSERVED, knowledge_cutoff=RETRIEVED,
    )
    assert len(prices) == 1
    assert prices[0]["price"] == 100
    assert prices[0]["source_provider"] == "synthetic_fixture"

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.recommendation_benchmark_return_service import (
    RecommendationBenchmarkReturnService,
)


def test_benchmark_ignores_prices_retrieved_after_evaluation_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "SPY",
            "companyName": "SPDR S&P 500 ETF Trust",
            "exchangeShortName": "ARCX",
            "instrumentType": "etf",
            "country": "United States",
            "regionKey": "america",
        }
    )
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    due = generated + timedelta(days=7)
    as_of = generated + timedelta(days=8)
    entry_observed = generated + timedelta(hours=1)
    exit_observed = due + timedelta(hours=1)

    with database.connect() as connection:
        for observed_at, price, retrieved_at, provider in (
            (
                entry_observed,
                100.0,
                entry_observed + timedelta(minutes=1),
                "known_capture",
            ),
            (
                exit_observed,
                110.0,
                exit_observed + timedelta(minutes=1),
                "known_capture",
            ),
            (
                exit_observed,
                9999.0,
                as_of + timedelta(days=1),
                "future_backfill",
            ),
        ):
            connection.execute(
                """
                INSERT INTO market_observations (
                    instrument_id, observed_at, close, source_provider, retrieved_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    instrument_id,
                    observed_at.isoformat(),
                    price,
                    provider,
                    retrieved_at.isoformat(),
                ),
            )

    result = RecommendationBenchmarkReturnService(database=database).calculate(
        benchmark_symbol="SPY",
        generated_at=generated,
        due_at=due,
        as_of=as_of,
    )

    assert result.status == "resolved"
    assert result.entry_price == pytest.approx(100.0)
    assert result.exit_price == pytest.approx(110.0)
    assert result.benchmark_return == pytest.approx(0.10)
    assert result.exit_price != pytest.approx(9999.0)

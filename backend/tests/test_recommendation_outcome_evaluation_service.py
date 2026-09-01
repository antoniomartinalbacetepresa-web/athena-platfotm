from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_history_repository import (
    RecommendationHistoryRepository,
)
from app.services.recommendation_outcome_evaluation_service import (
    RecommendationOutcomeEvaluationService,
)


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(
    database: AthenaDatabase,
    *,
    symbol: str = "AAPL",
    company_name: str = "Apple Inc.",
    instrument_type: str = "common_stock",
) -> int:
    return InstrumentRepository(database=database).upsert(
        {
            "symbol": symbol,
            "companyName": company_name,
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "instrumentType": instrument_type,
            "marketCap": 1000.0,
        }
    )


def _recommendation(
    database: AthenaDatabase,
    *,
    generated: datetime,
    instrument_id: int | None,
    benchmark_symbol: str | None = None,
) -> int:
    return RecommendationHistoryRepository(database=database).create_recommendation(
        symbol="AAPL",
        benchmark_symbol=benchmark_symbol,
        action="buy",
        score=80.0,
        conviction=0.8,
        horizon_days=90,
        generated_at=generated,
        data_cutoff_at=generated - timedelta(minutes=1),
        model_version="athena-v1",
        rationale={},
        input_snapshot={},
        instrument_id=instrument_id,
    )


def _price(
    database: AthenaDatabase,
    *,
    instrument_id: int,
    observed_at: datetime,
    close: float,
    adjusted_close: float | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id,
                observed_at,
                close,
                adjusted_close,
                source_provider,
                retrieved_at
            ) VALUES (?, ?, ?, ?, 'test_prices', ?)
            """,
            (
                instrument_id,
                observed_at.astimezone(timezone.utc).isoformat(),
                close,
                adjusted_close,
                observed_at.astimezone(timezone.utc).isoformat(),
            ),
        )


def test_outcome_evaluator_uses_first_prices_after_entry_and_due_date(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = _recommendation(
        database,
        generated=generated,
        instrument_id=instrument_id,
    )

    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(hours=1),
        close=100.0,
    )
    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(days=3),
        close=90.0,
    )
    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(days=7, hours=1),
        close=110.0,
    )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(
        as_of=generated + timedelta(days=8),
    )

    assert report.due_count == 1
    assert report.evaluated_count == 1
    assert report.skipped_count == 0
    assert report.evaluated[0]["recommendationId"] == recommendation_id
    assert report.evaluated[0]["horizonDays"] == 7
    assert report.evaluated[0]["entryPrice"] == pytest.approx(100.0)
    assert report.evaluated[0]["exitPrice"] == pytest.approx(110.0)
    assert report.evaluated[0]["realizedReturn"] == pytest.approx(0.10)
    assert report.evaluated[0]["maxDrawdown"] == pytest.approx(-0.10)
    assert report.evaluated[0]["benchmarkStatus"] == "benchmark_not_declared"

    outcomes = RecommendationHistoryRepository(
        database=database
    ).list_outcomes(recommendation_id)
    assert len(outcomes) == 1
    assert outcomes[0]["horizon_days"] == 7
    assert outcomes[0]["realized_return"] == pytest.approx(0.10)
    assert outcomes[0]["benchmark_return"] is None
    assert outcomes[0]["excess_return"] is None


def test_outcome_evaluator_prefers_raw_close_over_later_adjusted_close(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _recommendation(
        database,
        generated=generated,
        instrument_id=instrument_id,
    )

    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(hours=1),
        close=100.0,
        adjusted_close=50.0,
    )
    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(days=7, hours=1),
        close=110.0,
        adjusted_close=55.0,
    )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(
        as_of=generated + timedelta(days=8),
    )

    assert report.evaluated_count == 1
    assert report.evaluated[0]["entryPrice"] == pytest.approx(100.0)
    assert report.evaluated[0]["exitPrice"] == pytest.approx(110.0)
    assert report.to_api_dict()["pricePolicy"] == (
        "raw_close_first_adjusted_close_fallback"
    )


def test_outcome_evaluator_does_not_use_pre_due_price_as_exit(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _recommendation(
        database,
        generated=generated,
        instrument_id=instrument_id,
    )

    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(hours=1),
        close=100.0,
    )
    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(days=6),
        close=150.0,
    )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(
        as_of=generated + timedelta(days=8),
    )

    assert report.evaluated_count == 0
    assert report.skipped_missing_exit_price == 1


def test_outcome_evaluator_skips_recommendation_without_instrument_identity(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _recommendation(
        database,
        generated=generated,
        instrument_id=None,
    )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(
        as_of=generated + timedelta(days=8),
    )

    assert report.evaluated_count == 0
    assert report.skipped_missing_instrument == 1


def test_outcome_evaluator_calculates_peak_to_trough_max_drawdown(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _recommendation(
        database,
        generated=generated,
        instrument_id=instrument_id,
    )

    for offset, price in (
        (timedelta(hours=1), 100.0),
        (timedelta(days=2), 120.0),
        (timedelta(days=4), 90.0),
        (timedelta(days=7, hours=1), 110.0),
    ):
        _price(
            database,
            instrument_id=instrument_id,
            observed_at=generated + offset,
            close=price,
        )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(as_of=generated + timedelta(days=8))

    assert report.evaluated_count == 1
    assert report.evaluated[0]["maxDrawdown"] == pytest.approx(-0.25)


def test_outcome_evaluator_persists_frozen_benchmark_and_excess_return(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    benchmark_id = _instrument(
        database,
        symbol="SPY",
        company_name="SPDR S&P 500 ETF Trust",
        instrument_type="etf",
    )
    generated = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    recommendation_id = _recommendation(
        database,
        generated=generated,
        instrument_id=instrument_id,
        benchmark_symbol="SPY",
    )

    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(hours=1),
        close=100.0,
    )
    _price(
        database,
        instrument_id=instrument_id,
        observed_at=generated + timedelta(days=7, hours=1),
        close=110.0,
    )
    _price(
        database,
        instrument_id=benchmark_id,
        observed_at=generated + timedelta(hours=2),
        close=500.0,
    )
    _price(
        database,
        instrument_id=benchmark_id,
        observed_at=generated + timedelta(days=7, hours=2),
        close=525.0,
    )

    report = RecommendationOutcomeEvaluationService(
        database=database
    ).evaluate_due(as_of=generated + timedelta(days=8))

    assert report.evaluated_count == 1
    evaluated = report.evaluated[0]
    assert evaluated["benchmarkStatus"] == "resolved"
    assert evaluated["benchmarkSymbol"] == "SPY"
    assert evaluated["benchmarkReturn"] == pytest.approx(0.05)
    assert evaluated["excessReturn"] == pytest.approx(0.05)
    assert report.to_api_dict()["benchmarkStatus"] == (
        "evaluated_when_explicit_frozen_benchmark_is_resolvable"
    )

    outcomes = RecommendationHistoryRepository(
        database=database
    ).list_outcomes(recommendation_id)
    assert len(outcomes) == 1
    assert outcomes[0]["benchmark_return"] == pytest.approx(0.05)
    assert outcomes[0]["excess_return"] == pytest.approx(0.05)

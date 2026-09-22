from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.dividend_analysis_service import DividendAnalysisService


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase) -> int:
    return InstrumentRepository(database=database).upsert({
        "symbol": "DIV",
        "companyName": "Dividend Co",
        "country": "United States",
        "regionKey": "america",
        "exchangeShortName": "NYSE",
        "currency": "USD",
        "instrumentType": "EQUITY",
        "marketCap": 1000.0,
    })


def _save(database, instrument_id, provider, retrieved_at, dates):
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id,
        source_provider=provider,
        retrieved_at=retrieved_at,
        actions=[{
            "action_type": "dividend",
            "effective_at": date,
            "cash_amount": 0.25,
            "currency": "USD",
        } for date in dates],
    )


def test_quarterly_dividends_are_classified_and_duplicate_providers_count_once(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    known = datetime(2026, 8, 2, tzinfo=timezone.utc)
    dates = [
        datetime(2025, 8, 1, tzinfo=timezone.utc),
        datetime(2025, 11, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 1, tzinfo=timezone.utc),
    ]
    _save(database, instrument_id, "primary", known, dates)
    _save(database, instrument_id, "secondary", known, dates)

    result = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=known,
        pit_price=20.0,
    )

    assert result.payment_count == 5
    assert result.frequency == "quarterly"
    assert result.currency == "USD"
    assert result.currency_consistent is True
    assert result.trailing_cash_per_share == pytest.approx(1.0)
    assert result.trailing_yield == pytest.approx(0.05)
    assert result.annualized_cash_per_share == pytest.approx(1.0)
    assert result.regularity_score is not None and result.regularity_score > 0.95


def test_future_or_not_yet_known_dividend_cannot_leak_through_pit_cutoff(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _save(
        database,
        instrument_id,
        "primary",
        datetime(2026, 8, 2, tzinfo=timezone.utc),
        [datetime(2026, 5, 1, tzinfo=timezone.utc)],
    )

    result = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=cutoff,
    )

    assert result.payment_count == 0
    assert result.frequency == "none"
    assert result.trailing_cash_per_share == 0.0


def test_mixed_currency_history_does_not_sum_cash_as_if_comparable(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    repo = CorporateActionRepository(database=database)
    known = datetime(2026, 8, 2, tzinfo=timezone.utc)
    repo.save_many(
        instrument_id=instrument_id,
        source_provider="primary",
        retrieved_at=known,
        actions=[
            {"action_type": "dividend", "effective_at": datetime(2026, 2, 1, tzinfo=timezone.utc), "cash_amount": 1.0, "currency": "USD"},
            {"action_type": "dividend", "effective_at": datetime(2026, 5, 1, tzinfo=timezone.utc), "cash_amount": 1.0, "currency": "EUR"},
        ],
    )

    result = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=known,
    )

    assert result.currency_consistent is False
    assert result.currency is None
    assert result.trailing_cash_per_share == 0.0
    assert result.annualized_cash_per_share is None


def test_dividend_yield_requires_explicit_positive_pit_price(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    known = datetime(2026, 8, 2, tzinfo=timezone.utc)
    _save(
        database,
        instrument_id,
        "primary",
        known,
        [
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        ],
    )
    service = DividendAnalysisService(database=database)

    without_price = service.analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=known,
    )
    assert without_price.trailing_yield is None

    with pytest.raises(ValueError, match="pit_price"):
        service.analyze(
            instrument_id=instrument_id,
            knowledge_cutoff=known,
            pit_price=0.0,
        )


def test_mixed_currency_history_never_emits_dividend_yield(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database)
    repo = CorporateActionRepository(database=database)
    known = datetime(2026, 8, 2, tzinfo=timezone.utc)
    repo.save_many(
        instrument_id=instrument_id,
        source_provider="primary",
        retrieved_at=known,
        actions=[
            {"action_type": "dividend", "effective_at": datetime(2026, 2, 1, tzinfo=timezone.utc), "cash_amount": 1.0, "currency": "USD"},
            {"action_type": "dividend", "effective_at": datetime(2026, 5, 1, tzinfo=timezone.utc), "cash_amount": 1.0, "currency": "EUR"},
        ],
    )

    result = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=known,
        pit_price=20.0,
    )

    assert result.currency_consistent is False
    assert result.trailing_yield is None

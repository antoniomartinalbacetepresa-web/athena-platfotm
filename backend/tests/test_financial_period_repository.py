from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.financial_period_repository import FinancialPeriodRepository
from app.repositories.instrument_repository import InstrumentRepository


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase) -> int:
    return InstrumentRepository(database=database).upsert({
        "symbol":"AAPL", "companyName":"Apple Inc.", "country":"United States",
        "regionKey":"america", "exchangeShortName":"NMS", "instrumentType":"common_stock",
    })


def _period(source_timestamp: datetime) -> dict:
    return {
        "period_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "period_end": datetime(2025, 12, 31, tzinfo=timezone.utc),
        "currency": "USD", "net_income": 100.0, "free_cash_flow": 80.0,
        "source_timestamp": source_timestamp,
    }


def test_financial_period_is_invisible_before_it_was_known(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    filing = datetime(2026, 2, 1, tzinfo=timezone.utc)
    retrieved = filing + timedelta(minutes=5)
    stats = repo.save_many(instrument_id=instrument_id, periods=[_period(filing)], source_provider="sec_filing", retrieved_at=retrieved)
    assert stats.inserted == 1
    assert repo.list_for_instrument(instrument_id, knowledge_cutoff=filing) == []
    rows = repo.list_for_instrument(instrument_id, knowledge_cutoff=retrieved)
    assert len(rows) == 1 and rows[0]["net_income"] == 100.0 and rows[0]["free_cash_flow"] == 80.0
    assert rows[0]["source_provider"] == "sec_filing"


def test_financial_period_rejects_impossible_provenance_chronology(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    retrieved = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="source_timestamp"):
        repo.save_many(instrument_id=instrument_id, periods=[_period(retrieved + timedelta(seconds=1))], source_provider="filing", retrieved_at=retrieved)


def test_financial_period_storage_is_idempotent_and_currency_validated(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    filing = datetime(2026, 2, 1, tzinfo=timezone.utc); retrieved = filing + timedelta(minutes=1)
    first = repo.save_many(instrument_id=instrument_id, periods=[_period(filing)], source_provider="filing", retrieved_at=retrieved)
    second = repo.save_many(instrument_id=instrument_id, periods=[_period(filing)], source_provider="filing", retrieved_at=retrieved)
    assert first.inserted == 1 and second.inserted == 0 and second.unchanged == 1
    bad = _period(filing); bad["currency"] = "US"
    with pytest.raises(ValueError, match="currency"):
        repo.save_many(instrument_id=instrument_id, periods=[bad], source_provider="filing", retrieved_at=retrieved)


def test_financial_period_requires_at_least_one_fundamental_measure(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    filing = datetime(2026, 2, 1, tzinfo=timezone.utc); item = _period(filing)
    item["net_income"] = None; item["free_cash_flow"] = None
    with pytest.raises(ValueError, match="net_income"):
        repo.save_many(instrument_id=instrument_id, periods=[item], source_provider="filing", retrieved_at=filing)

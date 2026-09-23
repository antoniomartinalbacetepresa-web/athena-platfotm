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


def test_latest_financial_period_uses_only_restatement_known_at_cutoff(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    first_known = datetime(2026, 2, 1, tzinfo=timezone.utc)
    restated_known = datetime(2026, 3, 1, tzinfo=timezone.utc)
    first = _period(first_known); first["net_income"] = 100.0
    restated = _period(restated_known); restated["net_income"] = 90.0
    repo.save_many(instrument_id=instrument_id, periods=[first], source_provider="filing", retrieved_at=first_known)
    repo.save_many(instrument_id=instrument_id, periods=[restated], source_provider="filing", retrieved_at=restated_known)

    before = repo.list_latest_for_instrument(instrument_id, knowledge_cutoff=first_known)
    after = repo.list_latest_for_instrument(instrument_id, knowledge_cutoff=restated_known)
    immutable = repo.list_for_instrument(instrument_id, knowledge_cutoff=restated_known)
    assert len(before) == 1 and before[0]["net_income"] == 100.0
    assert len(after) == 1 and after[0]["net_income"] == 90.0
    assert len(immutable) == 2


def test_latest_financial_period_preserves_independent_providers(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    known = datetime(2026, 2, 1, tzinfo=timezone.utc)
    primary = _period(known); secondary = _period(known)
    primary["net_income"] = 100.0; secondary["net_income"] = 101.0
    repo.save_many(instrument_id=instrument_id, periods=[primary], source_provider="primary_filing", retrieved_at=known)
    repo.save_many(instrument_id=instrument_id, periods=[secondary], source_provider="independent_filing", retrieved_at=known)
    rows = repo.list_latest_for_instrument(instrument_id, knowledge_cutoff=known)
    assert len(rows) == 2
    assert {row["source_provider"] for row in rows} == {"primary_filing", "independent_filing"}

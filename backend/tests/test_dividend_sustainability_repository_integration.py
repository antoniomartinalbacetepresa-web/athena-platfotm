from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.financial_period_repository import FinancialPeriodRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.dividend_sustainability_service import DividendSustainabilityService


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase) -> int:
    return InstrumentRepository(database=database).upsert({
        "symbol": "AAPL", "companyName": "Apple Inc.", "country": "United States",
        "regionKey": "america", "exchangeShortName": "NMS", "instrumentType": "common_stock",
    })


def _period(*, known: datetime, net_income: float = 100.0, dividends_paid: float = 40.0) -> dict:
    return {
        "period_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "period_end": datetime(2025, 12, 31, tzinfo=timezone.utc),
        "currency": "USD", "net_income": net_income, "free_cash_flow": 80.0,
        "dividends_paid": dividends_paid, "source_timestamp": known,
    }


def test_latest_period_sustainability_uses_same_revision_and_provider(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    first = datetime(2026, 2, 1, tzinfo=timezone.utc); restated = datetime(2026, 3, 1, tzinfo=timezone.utc)
    repo.save_many(instrument_id=instrument_id, periods=[_period(known=first, net_income=100.0)], source_provider="issuer_filing", retrieved_at=first)
    repo.save_many(instrument_id=instrument_id, periods=[_period(known=restated, net_income=80.0)], source_provider="issuer_filing", retrieved_at=restated)
    service = DividendSustainabilityService(database=db)
    before = service.analyze_latest_period(instrument_id=instrument_id, knowledge_cutoff=first, source_provider="issuer_filing")
    after = service.analyze_latest_period(instrument_id=instrument_id, knowledge_cutoff=restated, source_provider="issuer_filing")
    assert before.earnings_payout_ratio == pytest.approx(0.40)
    assert after.earnings_payout_ratio == pytest.approx(0.50)
    assert before.fcf_payout_ratio == pytest.approx(0.50) == after.fcf_payout_ratio
    assert before.source_provider == "issuer_filing" == after.source_provider
    assert before.retrieved_at == first.isoformat() and after.retrieved_at == restated.isoformat()


def test_repository_backed_sustainability_never_auto_selects_independent_provider(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    known = datetime(2026, 2, 1, tzinfo=timezone.utc)
    repo.save_many(instrument_id=instrument_id, periods=[_period(known=known, net_income=100.0)], source_provider="primary_filing", retrieved_at=known)
    repo.save_many(instrument_id=instrument_id, periods=[_period(known=known, net_income=50.0)], source_provider="independent_filing", retrieved_at=known)
    service = DividendSustainabilityService(database=db)
    primary = service.analyze_latest_period(instrument_id=instrument_id, knowledge_cutoff=known, source_provider="primary_filing")
    independent = service.analyze_latest_period(instrument_id=instrument_id, knowledge_cutoff=known, source_provider="independent_filing")
    assert primary.earnings_payout_ratio == pytest.approx(0.40)
    assert independent.earnings_payout_ratio == pytest.approx(0.80)
    with pytest.raises(ValueError, match="source_provider"):
        service.analyze_latest_period(instrument_id=instrument_id, knowledge_cutoff=known, source_provider="")


def test_repository_backed_sustainability_fails_closed_before_filing_is_known(tmp_path: Path) -> None:
    db = _database(tmp_path); instrument_id = _instrument(db); repo = FinancialPeriodRepository(db)
    known = datetime(2026, 2, 1, tzinfo=timezone.utc); retrieved = known + timedelta(minutes=5)
    repo.save_many(instrument_id=instrument_id, periods=[_period(known=known)], source_provider="issuer_filing", retrieved_at=retrieved)
    result = DividendSustainabilityService(database=db).analyze_latest_period(
        instrument_id=instrument_id, knowledge_cutoff=known, source_provider="issuer_filing"
    )
    assert result.earnings_payout_ratio is None and result.fcf_payout_ratio is None
    assert result.sustainability_score is None and result.source_provider is None

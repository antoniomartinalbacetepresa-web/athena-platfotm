from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.dividend_analysis_service import DividendAnalysisService


def _setup(tmp_path: Path) -> tuple[AthenaDatabase, int]:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "FWD", "companyName": "Forward Dividend Co", "country": "United States",
        "regionKey": "america", "exchangeShortName": "NYSE", "currency": "USD",
        "instrumentType": "EQUITY", "marketCap": 1000.0,
    })
    return database, instrument_id


def test_confirmed_forward_is_separate_from_paid_and_preserves_provenance(tmp_path: Path) -> None:
    database, instrument_id = _setup(tmp_path)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    retrieved = datetime(2026, 5, 20, tzinfo=timezone.utc)
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id, source_provider="exchange_notice", retrieved_at=retrieved,
        actions=[{"action_type": "dividend", "effective_at": datetime(2026, 7, 1, tzinfo=timezone.utc), "cash_amount": 0.30, "currency": "USD"}],
    )
    result = DividendAnalysisService(database=database).analyze(instrument_id=instrument_id, knowledge_cutoff=cutoff, pit_price=20.0)
    assert result.payment_count == 0 and result.trailing_yield is None
    assert result.confirmed_forward_payment_count == 1
    assert result.confirmed_forward_cash_per_share == pytest.approx(0.30)
    assert result.confirmed_forward_yield == pytest.approx(0.015)
    assert result.confirmed_forward_source_providers == ("exchange_notice",)
    assert result.confirmed_forward_latest_retrieved_at == retrieved.isoformat()


def test_forward_discovered_after_cutoff_cannot_leak(tmp_path: Path) -> None:
    database, instrument_id = _setup(tmp_path)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id, source_provider="exchange_notice", retrieved_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        actions=[{"action_type": "dividend", "effective_at": datetime(2026, 7, 1, tzinfo=timezone.utc), "cash_amount": 0.30, "currency": "USD"}],
    )
    result = DividendAnalysisService(database=database).analyze(instrument_id=instrument_id, knowledge_cutoff=cutoff, pit_price=20.0)
    assert result.confirmed_forward_payment_count == 0
    assert result.confirmed_forward_cash_per_share is None
    assert result.confirmed_forward_yield is None


def test_mixed_currency_confirmed_forward_cash_fails_closed(tmp_path: Path) -> None:
    database, instrument_id = _setup(tmp_path)
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id, source_provider="notice", retrieved_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        actions=[
            {"action_type": "dividend", "effective_at": datetime(2026, 7, 1, tzinfo=timezone.utc), "cash_amount": 0.30, "currency": "USD"},
            {"action_type": "dividend", "effective_at": datetime(2026, 8, 1, tzinfo=timezone.utc), "cash_amount": 0.20, "currency": "EUR"},
        ],
    )
    result = DividendAnalysisService(database=database).analyze(instrument_id=instrument_id, knowledge_cutoff=cutoff, pit_price=20.0)
    assert result.confirmed_forward_payment_count == 2
    assert result.confirmed_forward_cash_per_share is None
    assert result.confirmed_forward_yield is None

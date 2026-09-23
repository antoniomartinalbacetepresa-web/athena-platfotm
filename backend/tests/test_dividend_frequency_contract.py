from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.dividend_analysis_service import DividendAnalysisService


@pytest.mark.parametrize(
    ("frequency", "spacing_days", "payment_count"),
    [
        ("monthly", 30, 8),
        ("quarterly", 91, 5),
        ("semiannual", 182, 3),
        ("annual", 365, 2),
    ],
)
def test_supported_dividend_cadences_are_explicit_pit_contract(
    tmp_path: Path,
    frequency: str,
    spacing_days: int,
    payment_count: int,
) -> None:
    database = AthenaDatabase(tmp_path / f"{frequency}.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "DIV",
            "companyName": "Dividend Co",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NYSE",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 1000.0,
        }
    )
    cutoff = datetime(2026, 8, 2, tzinfo=timezone.utc)
    latest = cutoff - timedelta(days=1)
    dates = [latest - timedelta(days=spacing_days * i) for i in reversed(range(payment_count))]
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id,
        source_provider="primary",
        retrieved_at=cutoff,
        actions=[
            {
                "action_type": "dividend",
                "effective_at": date,
                "cash_amount": 0.25,
                "currency": "USD",
            }
            for date in dates
        ],
    )

    payload = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=cutoff,
        pit_price=20.0,
    ).to_api_dict()

    assert payload["frequency"] == frequency
    assert payload["paymentCount"] == payment_count
    assert payload["currency"] == "USD"
    assert payload["currencyConsistent"] is True
    assert payload["pitSafe"] is True
    assert payload["knowledgeCutoff"] == cutoff.isoformat()
    assert payload["trailingYield"] is not None


def test_irregular_dividend_cadence_remains_irregular_without_projection(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "irregular.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "IRR",
            "companyName": "Irregular Dividend Co",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NYSE",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 1000.0,
        }
    )
    cutoff = datetime(2026, 8, 2, tzinfo=timezone.utc)
    dates = [
        datetime(2025, 9, 1, tzinfo=timezone.utc),
        datetime(2025, 9, 21, tzinfo=timezone.utc),
        datetime(2026, 7, 20, tzinfo=timezone.utc),
    ]
    CorporateActionRepository(database=database).save_many(
        instrument_id=instrument_id,
        source_provider="primary",
        retrieved_at=cutoff,
        actions=[
            {"action_type": "dividend", "effective_at": date, "cash_amount": 0.25, "currency": "USD"}
            for date in dates
        ],
    )

    payload = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=cutoff,
        pit_price=20.0,
    ).to_api_dict()

    assert payload["frequency"] == "irregular"
    assert payload["paymentStabilityScore"] is None
    assert payload["suspectedSuspension"] is None
    assert payload["confirmedForwardPaymentCount"] == 0
    assert payload["confirmedForwardCashPerShare"] is None
    assert payload["pitSafe"] is True

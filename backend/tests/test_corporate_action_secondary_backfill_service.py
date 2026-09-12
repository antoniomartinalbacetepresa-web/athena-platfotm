from __future__ import annotations

from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_secondary_backfill_service import (
    CorporateActionSecondaryBackfillService,
)


class FakeAlphaVantageProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(symbol)
        if symbol == "AAPL":
            return [
                {
                    "symbol": "AAPL",
                    "sourceProvider": "alpha_vantage",
                    "timestamp": "2026-08-10T00:00:00+00:00",
                    "retrievedAt": "2026-09-12T11:00:00+00:00",
                    "dividend": 0.25,
                    "stockSplit": None,
                }
            ]
        return []


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type,
                currency, is_active
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            ("AAPL", "Apple", "NASDAQ", "stock", "USD"),
        )
        connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type,
                currency, is_active
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            ("SPY", "SPDR S&P 500 ETF", "NYSEARCA", "etf", "USD"),
        )
    return database


def test_secondary_backfill_reuses_canonical_pit_repository_and_skips_funds(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    provider = FakeAlphaVantageProvider()
    progress: list[dict[str, object]] = []
    service = CorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        progress_callback=progress.append,
    )

    report = service.run(limit=10, from_date="2026-01-01", to_date="2026-09-12")

    assert report.selected_count == 2
    assert report.processed_count == 2
    assert report.persisted_instrument_count == 1
    assert report.skipped_non_equity_count == 1
    assert report.failed_count == 0
    assert report.actions_received == 1
    assert report.actions_inserted == 1
    assert provider.calls == ["AAPL"]
    assert [event["status"] for event in progress] == ["persisted", "skipped_non_equity"]

    with database.connect() as connection:
        instrument_id = int(
            connection.execute(
                "SELECT id FROM instruments WHERE symbol = 'AAPL'"
            ).fetchone()["id"]
        )
    rows = CorporateActionRepository(database).list_for_instrument(instrument_id)
    assert len(rows) == 1
    assert rows[0]["source_provider"] == "alpha_vantage"
    assert rows[0]["cash_amount"] == 0.25
    assert rows[0]["currency"] == "USD"

    api = report.to_api_dict()
    assert api["canonicalization"] == "forbidden"
    assert api["productionIndependenceClaimed"] is False


def test_secondary_backfill_reports_provider_failures_without_fabricating_success(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)

    class FailingProvider:
        def get_history(self, symbol, from_date=None, to_date=None):
            raise RuntimeError("secondary provider unavailable")

    report = CorporateActionSecondaryBackfillService(
        database=database,
        history_provider=FailingProvider(),
    ).run(limit=1)

    assert report.persisted_instrument_count == 0
    assert report.failed_count == 1
    assert report.actions_inserted == 0
    assert report.failures == (
        {"symbol": "AAPL", "error": "secondary provider unavailable"},
    )

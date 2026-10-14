from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.verified_corporate_action_secondary_backfill_service import (
    VerifiedCorporateActionSecondaryBackfillService,
)


AS_OF = datetime(2026, 9, 13, 19, 0, tzinfo=timezone.utc)
VERIFIED_AT = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
PRIMARY_RETRIEVED = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


class WrongFamilyProvider:
    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        del from_date, to_date
        return [
            {
                "symbol": symbol,
                "sourceProvider": "yahoo",
                "timestamp": "2026-08-15T00:00:00+00:00",
                "retrievedAt": "2026-09-13T19:30:00+00:00",
                "dividend": 0.25,
                "stockSplit": None,
            }
        ]


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def test_secondary_backfill_rejects_wrong_provider_family_before_persistence(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type,
                currency, is_active
            ) VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'stock', 'USD', 1)
            """
        )
        instrument_id = int(cursor.lastrowid)

    CorporateActionRepository(database).save_many(
        instrument_id=instrument_id,
        source_provider="yahoo",
        retrieved_at=PRIMARY_RETRIEVED,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": "2026-08-15T00:00:00+00:00",
                "cashAmount": 0.25,
                "currency": "USD",
            }
        ],
    )

    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=WrongFamilyProvider(),
        clock=lambda: VERIFIED_AT,
    ).run(as_of=AS_OF, limit=10)

    assert report.selected_event_count == 1
    assert report.failed_count == 1
    assert report.actions_received == 0
    assert report.actions_inserted == 0
    assert report.persisted_instrument_count == 0
    assert report.incomplete_before == 1
    assert report.incomplete_after == 1
    assert report.selected_events_still_incomplete == 1
    assert report.status == "completed_with_failures"
    assert "alpha_vantage" in report.failures[0]["error"]

    payload = report.to_api_dict()
    assert payload["policy"]["expectedSecondaryProviderFamily"] == "alpha_vantage"
    assert payload["policy"]["providerFamilyEnforced"] is True
    assert payload["policy"]["productionIndependenceClaimed"] is False
    assert payload["policy"]["automaticCanonicalization"] is False

    with database.connect() as connection:
        providers = {
            str(row["source_provider"])
            for row in connection.execute(
                "SELECT source_provider FROM corporate_actions WHERE instrument_id = ?",
                (instrument_id,),
            ).fetchall()
        }
    assert providers == {"yahoo"}

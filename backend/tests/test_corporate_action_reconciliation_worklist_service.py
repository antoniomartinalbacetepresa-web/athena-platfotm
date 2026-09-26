from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_reconciliation_worklist_service import (
    CorporateActionReconciliationWorklistService,
)


AS_OF = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _database(tmp_path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _instrument(database: AthenaDatabase, symbol: str) -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type
            ) VALUES (?, ?, 'NASDAQ', 'common_stock')
            """,
            (symbol, symbol),
        )
        return int(cursor.lastrowid)


def _save(
    database: AthenaDatabase,
    *,
    instrument_id: int,
    provider: str,
    effective_at: datetime,
    retrieved_at: datetime,
    amount: float = 0.25,
) -> None:
    CorporateActionRepository(database).save_many(
        instrument_id=instrument_id,
        source_provider=provider,
        retrieved_at=retrieved_at,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": effective_at.isoformat(),
                "cashAmount": amount,
                "currency": "USD",
            }
        ],
    )


def test_yahoo_only_event_becomes_actionable_alpha_vantage_work_item(tmp_path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAA")
    effective = AS_OF - timedelta(days=30)
    _save(
        database,
        instrument_id=instrument_id,
        provider="yahoo",
        effective_at=effective,
        retrieved_at=AS_OF - timedelta(days=20),
    )

    worklist = CorporateActionReconciliationWorklistService(database).get_worklist(
        as_of=AS_OF
    )

    assert worklist.total_incomplete_event_count == 1
    item = worklist.items[0]
    assert item.instrument_id == instrument_id
    assert item.symbol == "AAA"
    assert item.observed_providers == ("yahoo",)
    assert item.observed_provider_families == ("yahoo",)
    assert item.missing_independent_family_count == 1
    assert item.suggested_provider == "alpha_vantage"
    payload = worklist.to_api_dict()
    assert payload["status"] == "reconciliation_worklist_only"
    assert payload["policy"] == {
        "minimumIndependentProviderFamilies": 2,
        "automaticCanonicalization": False,
        "productionIndependenceClaimed": False,
        "automaticReadinessPromotion": False,
        "automaticTrading": False,
    }


def test_event_with_yahoo_and_alpha_vantage_is_removed_from_worklist(tmp_path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAA")
    effective = AS_OF - timedelta(days=30)
    retrieved = AS_OF - timedelta(days=20)
    _save(
        database,
        instrument_id=instrument_id,
        provider="yahoo",
        effective_at=effective,
        retrieved_at=retrieved,
    )
    _save(
        database,
        instrument_id=instrument_id,
        provider="alpha_vantage",
        effective_at=effective,
        retrieved_at=retrieved + timedelta(hours=1),
    )

    worklist = CorporateActionReconciliationWorklistService(database).get_worklist(
        as_of=AS_OF
    )

    assert worklist.total_incomplete_event_count == 0
    assert worklist.items == ()


def test_unclassified_provider_does_not_fake_independent_family(tmp_path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAA")
    effective = AS_OF - timedelta(days=30)
    _save(
        database,
        instrument_id=instrument_id,
        provider="yahoo",
        effective_at=effective,
        retrieved_at=AS_OF - timedelta(days=20),
    )
    _save(
        database,
        instrument_id=instrument_id,
        provider="mirror_feed",
        effective_at=effective,
        retrieved_at=AS_OF - timedelta(days=19),
    )

    worklist = CorporateActionReconciliationWorklistService(database).get_worklist(
        as_of=AS_OF
    )

    item = worklist.items[0]
    assert item.observed_provider_families == ("yahoo",)
    assert item.unclassified_providers == ("mirror_feed",)
    assert item.suggested_provider == "alpha_vantage"


def test_pit_cutoff_hides_secondary_evidence_not_known_yet(tmp_path) -> None:
    database = _database(tmp_path)
    instrument_id = _instrument(database, "AAA")
    effective = AS_OF - timedelta(days=30)
    _save(
        database,
        instrument_id=instrument_id,
        provider="yahoo",
        effective_at=effective,
        retrieved_at=AS_OF - timedelta(days=20),
    )
    _save(
        database,
        instrument_id=instrument_id,
        provider="alpha_vantage",
        effective_at=effective,
        retrieved_at=AS_OF + timedelta(days=1),
    )

    worklist = CorporateActionReconciliationWorklistService(database).get_worklist(
        as_of=AS_OF
    )

    assert worklist.total_incomplete_event_count == 1
    assert worklist.items[0].observed_providers == ("yahoo",)


def test_worklist_pagination_and_aware_cutoff_are_fail_closed(tmp_path) -> None:
    database = _database(tmp_path)
    first_id = _instrument(database, "AAA")
    second_id = _instrument(database, "BBB")
    effective = AS_OF - timedelta(days=30)
    for instrument_id in (first_id, second_id):
        _save(
            database,
            instrument_id=instrument_id,
            provider="yahoo",
            effective_at=effective,
            retrieved_at=AS_OF - timedelta(days=20),
        )

    service = CorporateActionReconciliationWorklistService(database)
    page = service.get_worklist(as_of=AS_OF, limit=1, offset=1)
    assert page.total_incomplete_event_count == 2
    assert [item.symbol for item in page.items] == ["BBB"]
    assert page.to_api_dict()["hasMore"] is False

    with pytest.raises(ValueError, match="zona horaria"):
        service.get_worklist(as_of=datetime(2026, 9, 13, 12, 0))
    with pytest.raises(ValueError, match="limit"):
        service.get_worklist(as_of=AS_OF, limit=0)
    with pytest.raises(ValueError, match="offset"):
        service.get_worklist(as_of=AS_OF, offset=-1)

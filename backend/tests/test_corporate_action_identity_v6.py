from __future__ import annotations

from datetime import datetime, timezone

from app.database.athena_database_v5 import AthenaDatabase as AthenaDatabaseV5
from app.database.athena_database_v6 import AthenaDatabase as AthenaDatabaseV6
from app.repositories.corporate_action_repository import CorporateActionRepository


RETRIEVED_AT = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
EFFECTIVE_AT = "2026-08-15T00:00:00+00:00"


def _insert_instrument(database) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type
            ) VALUES ('TEST', 'Test Issuer', 'TESTX', 'equity')
            """
        )


def test_distinct_same_time_dividends_are_not_silently_deduplicated(tmp_path) -> None:
    database = AthenaDatabaseV6(tmp_path / "athena.db")
    database.initialize()
    _insert_instrument(database)
    repository = CorporateActionRepository(database)
    actions = [
        {
            "type": "dividend",
            "effectiveAt": EFFECTIVE_AT,
            "cashAmount": 0.25,
            "currency": "USD",
        },
        {
            "type": "dividend",
            "effectiveAt": EFFECTIVE_AT,
            "cashAmount": 0.10,
            "currency": "USD",
        },
    ]

    first = repository.save_many(
        instrument_id=1,
        actions=actions,
        source_provider="exchange_notice",
        retrieved_at=RETRIEVED_AT,
    )
    replay = repository.save_many(
        instrument_id=1,
        actions=actions,
        source_provider="exchange_notice",
        retrieved_at=RETRIEVED_AT,
    )

    assert first.inserted == 2
    assert replay.inserted == 0
    assert replay.unchanged == 2
    rows = repository.list_for_instrument(1)
    assert sorted(row["cash_amount"] for row in rows) == [0.10, 0.25]
    assert len({row["event_identity"] for row in rows}) == 2


def test_v5_to_v6_migration_preserves_existing_pit_action_and_idempotency(tmp_path) -> None:
    path = tmp_path / "athena.db"
    old_database = AthenaDatabaseV5(path)
    old_database.initialize()
    _insert_instrument(old_database)
    old_repository = CorporateActionRepository(old_database)
    action = {
        "type": "dividend",
        "effectiveAt": EFFECTIVE_AT,
        "cashAmount": 0.25,
        "currency": "USD",
    }
    old_repository.save_many(
        instrument_id=1,
        actions=[action],
        source_provider="yahoo_finance",
        retrieved_at=RETRIEVED_AT,
    )

    database = AthenaDatabaseV6(path)
    database.initialize()
    repository = CorporateActionRepository(database)
    rows = repository.list_for_instrument(1)

    assert database.SCHEMA_VERSION == 6
    assert len(rows) == 1
    assert rows[0]["cash_amount"] == 0.25
    assert rows[0]["event_identity"] == "dividend|0.25||USD"

    replay = repository.save_many(
        instrument_id=1,
        actions=[action],
        source_provider="yahoo_finance",
        retrieved_at=RETRIEVED_AT,
    )
    assert replay.inserted == 0
    assert replay.unchanged == 1
    assert len(repository.list_for_instrument(1)) == 1

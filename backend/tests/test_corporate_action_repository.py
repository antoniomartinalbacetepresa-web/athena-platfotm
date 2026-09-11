from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository


def _database(tmp_path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type
            ) VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'equity')
            """
        )
    return database


def test_persists_dividend_and_split_with_provenance(tmp_path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)
    retrieved_at = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    stats = repository.save_many(
        instrument_id=1,
        source_provider="yahoo_finance",
        retrieved_at=retrieved_at,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": "2026-08-15T00:00:00+00:00",
                "cashAmount": 0.25,
                "currency": "usd",
                "sourceTimestamp": "2026-09-10T12:00:00+00:00",
            },
            {
                "type": "split",
                "effectiveAt": "2020-08-31T00:00:00+00:00",
                "splitRatio": 4.0,
            },
        ],
    )

    assert stats.received == 2
    assert stats.inserted == 2
    assert stats.unchanged == 0

    rows = repository.list_for_instrument(1)
    assert [row["action_type"] for row in rows] == ["split", "dividend"]
    assert rows[0]["split_ratio"] == 4.0
    assert rows[1]["cash_amount"] == 0.25
    assert rows[1]["currency"] == "USD"
    assert all(row["source_provider"] == "yahoo_finance" for row in rows)
    assert all(row["retrieved_at"] == retrieved_at.isoformat() for row in rows)


def test_same_retrieval_is_idempotent(tmp_path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)
    retrieved_at = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    action = {
        "type": "split",
        "effectiveAt": "2020-08-31T00:00:00+00:00",
        "splitRatio": 4.0,
    }

    first = repository.save_many(
        instrument_id=1,
        actions=[action],
        source_provider="yahoo_finance",
        retrieved_at=retrieved_at,
    )
    second = repository.save_many(
        instrument_id=1,
        actions=[action],
        source_provider="yahoo_finance",
        retrieved_at=retrieved_at,
    )

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.unchanged == 1
    assert len(repository.list_for_instrument(1)) == 1


def test_pit_cutoff_blocks_retrospectively_discovered_action(tmp_path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)

    repository.save_many(
        instrument_id=1,
        source_provider="yahoo_finance",
        retrieved_at=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
        actions=[
            {
                "type": "split",
                "effectiveAt": "2020-08-31T00:00:00+00:00",
                "splitRatio": 4.0,
            }
        ],
    )

    historical_view = repository.list_for_instrument(
        1,
        knowledge_cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    known_view = repository.list_for_instrument(
        1,
        knowledge_cutoff=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )

    assert historical_view == []
    assert len(known_view) == 1


def test_future_effective_action_is_not_visible_before_effective_date(tmp_path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)

    repository.save_many(
        instrument_id=1,
        source_provider="exchange_notice",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        actions=[
            {
                "type": "dividend",
                "effectiveAt": "2026-09-30T00:00:00+00:00",
                "cashAmount": 0.30,
                "currency": "USD",
            }
        ],
    )

    assert repository.list_for_instrument(
        1,
        knowledge_cutoff=datetime(2026, 9, 15, tzinfo=timezone.utc),
    ) == []

    assert len(
        repository.list_for_instrument(
            1,
            knowledge_cutoff=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ) == 1


def test_rejects_source_timestamp_after_retrieval(tmp_path) -> None:
    repository = CorporateActionRepository(_database(tmp_path))

    with pytest.raises(ValueError, match="source_timestamp"):
        repository.save_many(
            instrument_id=1,
            source_provider="yahoo_finance",
            retrieved_at=datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
            actions=[
                {
                    "type": "dividend",
                    "effectiveAt": "2026-08-15T00:00:00+00:00",
                    "cashAmount": 0.25,
                    "sourceTimestamp": "2026-09-12T00:00:00+00:00",
                }
            ],
        )


def test_rejects_invalid_action_payloads(tmp_path) -> None:
    repository = CorporateActionRepository(_database(tmp_path))
    retrieved_at = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

    invalid_actions = [
        {"type": "dividend", "effectiveAt": "2026-08-15T00:00:00+00:00"},
        {
            "type": "split",
            "effectiveAt": "2020-08-31T00:00:00+00:00",
            "splitRatio": 0,
        },
        {
            "type": "merger",
            "effectiveAt": "2026-01-01T00:00:00+00:00",
            "cashAmount": 1.0,
        },
    ]

    for action in invalid_actions:
        with pytest.raises(ValueError):
            repository.save_many(
                instrument_id=1,
                source_provider="test",
                retrieved_at=retrieved_at,
                actions=[action],
            )


def test_repository_creates_durable_indexes(tmp_path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)

    repository.list_for_instrument(1)

    with database.connect() as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corporate_actions'"
        ).fetchone()
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='corporate_actions'"
            ).fetchall()
        }

    assert table is not None
    assert "idx_corporate_actions_instrument_effective" in indexes
    assert "idx_corporate_actions_pit" in indexes

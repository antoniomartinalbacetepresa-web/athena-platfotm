from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.verified_corporate_action_secondary_backfill_service import (
    VerifiedCorporateActionSecondaryBackfillService,
)


AS_OF = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
VERIFICATION_AT = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
RETRIEVED_BEFORE = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
TARGET_EFFECTIVE = "2026-08-15T00:00:00+00:00"
UNRELATED_EFFECTIVE = "2026-08-20T00:00:00+00:00"


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type, currency
            ) VALUES ('TARGET', 'Target Corp', 'NASDAQ', 'common_stock', 'USD')
            """
        )
        connection.execute(
            """
            INSERT INTO instruments (
                symbol, company_name, exchange_short_name, instrument_type, currency
            ) VALUES ('OTHER', 'Other Corp', 'NASDAQ', 'common_stock', 'USD')
            """
        )
    return database


def _save_dividend(
    repository: CorporateActionRepository,
    *,
    instrument_id: int,
    provider: str,
    effective_at: str,
    amount: float,
    retrieved_at: datetime,
) -> None:
    repository.save_many(
        instrument_id=instrument_id,
        source_provider=provider,
        retrieved_at=retrieved_at,
        actions=[
            {
                "type": "dividend",
                "effectiveAt": effective_at,
                "cashAmount": amount,
                "currency": "USD",
            }
        ],
    )


class ConflictOffsettingProvider:
    """Creates a target conflict while resolving an unrelated pre-existing one."""

    def __init__(self, repository: CorporateActionRepository) -> None:
        self._repository = repository
        self.calls: list[str] = []

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(symbol)
        assert symbol == "TARGET"

        # The unrelated event starts conflicted (Yahoo=0.50, AV=0.60). A newer
        # Alpha Vantage observation resolves it to 0.50 during this same run.
        _save_dividend(
            self._repository,
            instrument_id=2,
            provider="alpha_vantage",
            effective_at=UNRELATED_EFFECTIVE,
            amount=0.50,
            retrieved_at=VERIFICATION_AT,
        )

        # The selected target event becomes a new cross-family conflict.
        return [
            {
                "symbol": "TARGET",
                "timestamp": TARGET_EFFECTIVE,
                "retrievedAt": VERIFICATION_AT.isoformat(),
                "sourceProvider": "alpha_vantage",
                "dividend": 0.30,
                "stockSplit": None,
            }
        ]


def test_targeted_conflict_cannot_be_hidden_by_global_conflict_offset(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = CorporateActionRepository(database)

    # TARGET is the only incomplete event and therefore the only backfill target.
    _save_dividend(
        repository,
        instrument_id=1,
        provider="yahoo",
        effective_at=TARGET_EFFECTIVE,
        amount=0.25,
        retrieved_at=RETRIEVED_BEFORE,
    )

    # OTHER already has two families but they disagree before the run.
    _save_dividend(
        repository,
        instrument_id=2,
        provider="yahoo",
        effective_at=UNRELATED_EFFECTIVE,
        amount=0.50,
        retrieved_at=RETRIEVED_BEFORE,
    )
    _save_dividend(
        repository,
        instrument_id=2,
        provider="alpha_vantage",
        effective_at=UNRELATED_EFFECTIVE,
        amount=0.60,
        retrieved_at=RETRIEVED_BEFORE,
    )

    provider = ConflictOffsettingProvider(repository)
    report = VerifiedCorporateActionSecondaryBackfillService(
        database=database,
        history_provider=provider,
        clock=lambda: VERIFICATION_AT,
    ).run(as_of=AS_OF, limit=10)

    assert provider.calls == ["TARGET"]
    assert report.selected_event_count == 1
    assert report.selected_events_still_incomplete == 0

    # Aggregate conflict count is unchanged: old conflict resolved, new target
    # conflict appeared. Aggregate-delta logic would miss this exact condition.
    assert report.conflicts_before == 1
    assert report.conflicts_after == 1
    assert report.selected_events_conflicting == 1
    assert report.status == "targeted_secondary_conflict_detected"

    payload = report.to_api_dict()
    assert payload["reconciliation"]["selectedEventsConflicting"] == 1
    assert payload["policy"]["eventLevelConflictVerification"] is True
    assert payload["policy"]["automaticCanonicalization"] is False
    assert payload["policy"]["automaticReadinessPromotion"] is False

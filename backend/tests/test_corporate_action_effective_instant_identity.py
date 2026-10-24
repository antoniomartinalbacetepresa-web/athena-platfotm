from datetime import datetime, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_coverage_service import CorporateActionCoverageService


def test_equivalent_effective_instants_reconcile_across_provider_timezones(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) "
            "VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'equity')"
        )
    repository = CorporateActionRepository(database)
    retrieved = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)
    for provider, effective_at in (
        ("yahoo", "2026-08-15T00:00:00+00:00"),
        ("exchange_notice", "2026-08-14T20:00:00-04:00"),
    ):
        repository.save_many(
            instrument_id=1,
            source_provider=provider,
            retrieved_at=retrieved,
            actions=[{
                "type": "dividend",
                "effectiveAt": effective_at,
                "cashAmount": 0.25,
                "currency": "USD",
            }],
        )

    report = CorporateActionCoverageService(
        database=database,
        provider_families={"yahoo": "yahoo", "exchange_notice": "exchange"},
    ).get_report(as_of=datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc))

    assert report.event_count == 1
    assert report.agreed_event_count == 1
    assert report.incomplete_event_count == 0
    assert report.conflict_event_count == 0
    assert report.cross_provider_reconciliation_ready is True
    assert report.to_api_dict()["productionIndependenceClaimed"] is False

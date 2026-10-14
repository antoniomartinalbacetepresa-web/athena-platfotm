from datetime import datetime, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.dividend_analysis_service import DividendAnalysisService


def test_no_cut_streak_uses_only_observed_annual_windows(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) VALUES ('DIV', 'Dividend Co', 'TEST', 'equity')")
        instrument_id = int(connection.execute("SELECT id FROM instruments WHERE symbol = 'DIV'").fetchone()["id"])

    cutoff = datetime(2026, 9, 1, tzinfo=timezone.utc)
    repository = CorporateActionRepository(database=database)
    actions = []
    # Three complete annual windows, oldest to newest: 0.80, 1.00, 1.20 cash/share.
    for effective_at, amount in (
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 0.40),
        (datetime(2024, 4, 1, tzinfo=timezone.utc), 0.40),
        (datetime(2025, 1, 1, tzinfo=timezone.utc), 0.50),
        (datetime(2025, 4, 1, tzinfo=timezone.utc), 0.50),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.60),
        (datetime(2026, 4, 1, tzinfo=timezone.utc), 0.60),
    ):
        actions.append({"action_type": "dividend", "effective_at": effective_at, "cash_amount": amount, "currency": "USD"})
    repository.save_many(instrument_id=instrument_id, source_provider="test", retrieved_at=cutoff, actions=actions)

    result = DividendAnalysisService(database=database).analyze(
        instrument_id=instrument_id,
        knowledge_cutoff=cutoff,
        lookback_days=1095,
    )

    assert result.cut_detected is False
    assert result.consecutive_full_years_without_cut == 2


def test_no_cut_streak_stops_at_older_cut(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO instruments (symbol, company_name, exchange_short_name, instrument_type) VALUES ('CUT', 'Cut Co', 'TEST', 'equity')")
        instrument_id = int(connection.execute("SELECT id FROM instruments WHERE symbol = 'CUT'").fetchone()["id"])

    cutoff = datetime(2026, 9, 1, tzinfo=timezone.utc)
    repository = CorporateActionRepository(database=database)
    # Oldest -> newest annual cash: 1.20, 0.80, 1.00. Latest comparison is healthy,
    # but the streak must stop when the preceding historical cut is encountered.
    actions = []
    for effective_at, amount in (
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 0.60),
        (datetime(2024, 4, 1, tzinfo=timezone.utc), 0.60),
        (datetime(2025, 1, 1, tzinfo=timezone.utc), 0.40),
        (datetime(2025, 4, 1, tzinfo=timezone.utc), 0.40),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 0.50),
        (datetime(2026, 4, 1, tzinfo=timezone.utc), 0.50),
    ):
        actions.append({"action_type": "dividend", "effective_at": effective_at, "cash_amount": amount, "currency": "USD"})
    repository.save_many(instrument_id=instrument_id, source_provider="test", retrieved_at=cutoff, actions=actions)

    result = DividendAnalysisService(database=database).analyze(instrument_id=instrument_id, knowledge_cutoff=cutoff, lookback_days=1095)
    assert result.cut_detected is False
    assert result.consecutive_full_years_without_cut == 1

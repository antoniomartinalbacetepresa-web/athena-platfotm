from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.recommendation_market_signal_service import (
    RecommendationMarketSignalService,
)


def _build_database(tmp_path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _insert_instrument(database: AthenaDatabase, symbol: str = "TEST") -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                is_active
            ) VALUES (?, ?, ?, 'equity', 1)
            """,
            (symbol, f"{symbol} Company", "NASDAQ"),
        )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_observation(
    database: AthenaDatabase,
    *,
    instrument_id: int,
    observed_at: datetime,
    retrieved_at: datetime,
    price: float,
    provider: str = "test",
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO market_observations (
                instrument_id,
                observed_at,
                close,
                source_provider,
                retrieved_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                observed_at.isoformat(),
                price,
                provider,
                retrieved_at.isoformat(),
            ),
        )


def test_signal_uses_only_information_retrieved_by_as_of(tmp_path) -> None:
    database = _build_database(tmp_path)
    instrument_id = _insert_instrument(database)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for day in range(61):
        observed = start + timedelta(days=day)
        _insert_observation(
            database,
            instrument_id=instrument_id,
            observed_at=observed,
            retrieved_at=observed + timedelta(hours=1),
            price=100.0 + day,
            provider="historical_source",
        )

    as_of = start + timedelta(days=60, hours=12)
    _insert_observation(
        database,
        instrument_id=instrument_id,
        observed_at=start + timedelta(days=60),
        retrieved_at=as_of + timedelta(days=1),
        price=9999.0,
        provider="future_backfill",
    )

    result = RecommendationMarketSignalService(database=database).evaluate(
        symbol="test",
        as_of=as_of,
    )

    assert result.status == "diagnostic_ready"
    assert result.production_eligible is False
    assert result.observation_count == 61
    assert result.latest_price == pytest.approx(160.0)
    assert result.latest_retrieved_at == (start + timedelta(days=60, hours=1)).isoformat()
    assert result.source_providers == ("historical_source",)
    assert "future_backfill" not in result.source_providers
    assert result.return_20d == pytest.approx((160.0 / 140.0) - 1.0)
    assert result.return_60d == pytest.approx(0.6)
    assert result.technical_score is not None
    assert result.risk_score is not None
    payload = result.to_api_dict()
    assert payload["sourceProviders"] == ["historical_source"]
    assert payload["latestRetrievedAt"] == result.latest_retrieved_at


def test_signal_reports_all_selected_point_in_time_providers(tmp_path) -> None:
    database = _build_database(tmp_path)
    instrument_id = _insert_instrument(database)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for day in range(61):
        observed = start + timedelta(days=day)
        _insert_observation(
            database,
            instrument_id=instrument_id,
            observed_at=observed,
            retrieved_at=observed + timedelta(hours=1),
            price=100.0 + day,
            provider="source_a" if day < 30 else "source_b",
        )

    result = RecommendationMarketSignalService(database=database).evaluate(
        symbol="TEST",
        as_of=start + timedelta(days=60, hours=2),
    )

    assert result.status == "diagnostic_ready"
    assert result.source_providers == ("source_a", "source_b")


def test_signal_refuses_to_fill_missing_history(tmp_path) -> None:
    database = _build_database(tmp_path)
    instrument_id = _insert_instrument(database)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for day in range(20):
        observed = start + timedelta(days=day)
        _insert_observation(
            database,
            instrument_id=instrument_id,
            observed_at=observed,
            retrieved_at=observed + timedelta(hours=1),
            price=100.0 + day,
        )

    result = RecommendationMarketSignalService(database=database).evaluate(
        symbol="TEST",
        as_of=start + timedelta(days=30),
    )

    assert result.status == "insufficient_history"
    assert result.production_eligible is False
    assert result.observation_count == 20
    assert result.source_providers == ("test",)
    assert result.technical_score is None
    assert result.risk_score is None


def test_signal_rejects_ambiguous_symbol(tmp_path) -> None:
    database = _build_database(tmp_path)
    _insert_instrument(database, "DUAL")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                exchange_short_name,
                instrument_type,
                is_active
            ) VALUES ('DUAL', 'Dual Two', 'NYSE', 'equity', 1)
            """
        )

    result = RecommendationMarketSignalService(database=database).evaluate(
        symbol="DUAL",
        as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    assert result.status == "instrument_ambiguous"
    assert result.production_eligible is False
    assert result.instrument_id is None
    assert result.source_providers == ()


def test_signal_requires_timezone_aware_as_of(tmp_path) -> None:
    database = _build_database(tmp_path)
    service = RecommendationMarketSignalService(database=database)

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(symbol="TEST", as_of=datetime(2026, 3, 1))

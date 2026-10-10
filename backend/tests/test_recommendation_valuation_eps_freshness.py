from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.normalized_data_repository import NormalizedDataRepository
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)


def _eps(*, metric: str, value: float, effective_at: str, available_at: str) -> NormalizedDatum:
    return NormalizedDatum(
        metric=metric,
        value=value,
        data_kind="fact",
        provenance=DataProvenance(
            source_id="sec_edgar_xbrl",
            retrieved_at="2026-01-01T00:00:00+00:00",
            effective_at=effective_at,
            published_at=available_at[:10],
            source_timestamp=available_at[:10],
            available_at=available_at,
            version="10-K|0000320193-25-000001|CY2025",
        ),
        unit="USD/shares",
        entity_id="sec-cik:0000320193",
        quality_score=100.0,
    )


def test_latest_period_wins_before_xbrl_tag_preference(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    NormalizedDataRepository(database).save_many(
        [
            _eps(
                metric="fundamental.us-gaap.earningspersharediluted",
                value=4.0,
                effective_at="2024-09-28",
                available_at="2024-11-02T00:00:00+00:00",
            ),
            _eps(
                metric="fundamental.us-gaap.earningspersharebasicanddiluted",
                value=8.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
        ]
    )

    fact = RecommendationValuationSignalService(
        database=database
    )._latest_annual_diluted_eps(
        entity_id="sec-cik:0000320193",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert fact is not None
    assert fact.value == pytest.approx(8.0)
    assert fact.effective_at == "2025-09-27"
    assert fact.metric == "fundamental.us-gaap.earningspersharebasicanddiluted"


def test_tag_preference_only_breaks_ties_within_same_period(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    NormalizedDataRepository(database).save_many(
        [
            _eps(
                metric="fundamental.us-gaap.earningspersharebasicanddiluted",
                value=7.5,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _eps(
                metric="fundamental.us-gaap.earningspersharediluted",
                value=8.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
        ]
    )

    fact = RecommendationValuationSignalService(
        database=database
    )._latest_annual_diluted_eps(
        entity_id="sec-cik:0000320193",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert fact is not None
    assert fact.value == pytest.approx(8.0)
    assert fact.metric == "fundamental.us-gaap.earningspersharediluted"

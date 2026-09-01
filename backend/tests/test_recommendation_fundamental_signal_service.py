from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.normalized_data_repository import NormalizedDataRepository
from app.services.recommendation_fundamental_signal_service import (
    RecommendationFundamentalSignalService,
)
from app.services.sec_issuer_identity_service import SecIssuerIdentityService


class FakeSecProvider:
    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        return [
            {
                "cik": "0000320193",
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "exchange": "Nasdaq",
            }
        ]


def _listing(database: AthenaDatabase, *, symbol: str = "AAPL") -> int:
    return InstrumentRepository(database=database).upsert(
        {
            "symbol": symbol,
            "companyName": f"{symbol} Listing",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 100.0,
        }
    )


def _fundamental(
    *,
    metric: str,
    value: float,
    effective_at: str,
    available_at: str,
) -> NormalizedDatum:
    return NormalizedDatum(
        metric=metric,
        value=value,
        data_kind="fact",
        provenance=DataProvenance(
            source_id="sec_edgar_xbrl",
            retrieved_at="2026-01-10T12:00:00+00:00",
            effective_at=effective_at,
            published_at=available_at[:10],
            source_timestamp=available_at[:10],
            available_at=available_at,
            version=f"10-K|{effective_at}",
        ),
        unit="USD",
        entity_id="sec-cik:0000320193",
        quality_score=100.0,
    )


def _database_with_identity(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _listing(database)
    SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider(),
    ).apply()
    return database


def test_fundamental_signal_uses_only_point_in_time_available_facts(
    tmp_path: Path,
) -> None:
    database = _database_with_identity(tmp_path)
    repository = NormalizedDataRepository(database)
    repository.save_many(
        [
            _fundamental(
                metric=(
                    "fundamental.us-gaap."
                    "revenuefromcontractwithcustomerexcludingassessedtax"
                ),
                value=100.0,
                effective_at="2024-09-28",
                available_at="2024-11-02T00:00:00+00:00",
            ),
            _fundamental(
                metric=(
                    "fundamental.us-gaap."
                    "revenuefromcontractwithcustomerexcludingassessedtax"
                ),
                value=120.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.netincomeloss",
                value=24.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.assets",
                value=200.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.liabilities",
                value=80.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric=(
                    "fundamental.us-gaap."
                    "revenuefromcontractwithcustomerexcludingassessedtax"
                ),
                value=9999.0,
                effective_at="2026-09-26",
                available_at="2026-11-01T00:00:00+00:00",
            ),
        ]
    )

    signal = RecommendationFundamentalSignalService(database=database).evaluate(
        symbol="AAPL",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert signal.status == "diagnostic_ready"
    assert signal.entity_id == "sec-cik:0000320193"
    assert signal.coverage_ratio == pytest.approx(1.0)
    assert signal.mean_quality_score == pytest.approx(100.0)
    assert signal.revenue_growth == pytest.approx(0.20)
    assert signal.net_margin == pytest.approx(0.20)
    assert signal.liabilities_to_assets == pytest.approx(0.40)
    assert signal.production_eligible is False
    facts = {fact.key: fact.value for fact in signal.facts}
    assert facts["revenue"] == pytest.approx(120.0)
    assert 9999.0 not in facts.values()


def test_fundamental_signal_blocks_when_sec_identity_is_missing(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _listing(database)

    signal = RecommendationFundamentalSignalService(database=database).evaluate(
        symbol="AAPL",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert signal.status == "issuer_identity_missing"
    assert signal.coverage_ratio == 0.0
    assert signal.facts == ()
    assert signal.production_eligible is False


def test_fundamental_ratios_require_matching_effective_periods(tmp_path: Path) -> None:
    database = _database_with_identity(tmp_path)
    repository = NormalizedDataRepository(database)
    repository.save_many(
        [
            _fundamental(
                metric=(
                    "fundamental.us-gaap."
                    "revenuefromcontractwithcustomerexcludingassessedtax"
                ),
                value=120.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.netincomeloss",
                value=24.0,
                effective_at="2025-06-28",
                available_at="2025-08-02T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.assets",
                value=200.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _fundamental(
                metric="fundamental.us-gaap.liabilities",
                value=80.0,
                effective_at="2025-06-28",
                available_at="2025-08-02T00:00:00+00:00",
            ),
        ]
    )

    signal = RecommendationFundamentalSignalService(database=database).evaluate(
        symbol="AAPL",
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert signal.status == "diagnostic_ready"
    assert signal.net_margin is None
    assert signal.liabilities_to_assets is None


def test_fundamental_signal_rejects_naive_as_of(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    service = RecommendationFundamentalSignalService(database=database)

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=datetime(2026, 1, 1),
        )

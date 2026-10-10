from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.normalized_data_repository import NormalizedDataRepository
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)
from app.services.sec_issuer_identity_service import SecIssuerIdentityService


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


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


@dataclass(frozen=True)
class _MarketDiagnostic:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _MarketService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _MarketDiagnostic:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _MarketDiagnostic(self.payload)


def _market_payload(
    *,
    status: str = "diagnostic_ready",
    instrument_id: int = 1,
    price: float = 200.0,
    production_eligible: bool = False,
) -> dict[str, object]:
    return {
        "status": status,
        "symbol": "AAPL",
        "instrumentId": instrument_id,
        "asOf": AS_OF.isoformat(),
        "latestPrice": price,
        "latestObservedAt": "2025-12-31T21:00:00+00:00",
        "latestRetrievedAt": "2025-12-31T22:00:00+00:00",
        "sourceProviders": ["yahoo_finance"],
        "productionEligible": production_eligible,
    }


def _database_with_identity(tmp_path: Path) -> tuple[AthenaDatabase, int]:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NMS",
            "marketCap": 999999999.0,
        }
    )
    SecIssuerIdentityService(
        database=database,
        sec_provider=FakeSecProvider(),
    ).apply()
    return database, instrument_id


def _eps(
    *,
    value: float,
    effective_at: str,
    available_at: str,
    form: str = "10-K",
    metric: str = "fundamental.us-gaap.earningspersharediluted",
    unit: str = "USD/shares",
) -> NormalizedDatum:
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
            version=f"{form}|0000320193-25-000001|CY2025",
        ),
        unit=unit,
        entity_id="sec-cik:0000320193",
        quality_score=100.0,
    )


def test_valuation_uses_latest_available_annual_diluted_eps_without_lookahead(
    tmp_path: Path,
) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    repository = NormalizedDataRepository(database)
    repository.save_many(
        [
            _eps(
                value=5.0,
                effective_at="2024-09-28",
                available_at="2024-11-02T00:00:00+00:00",
            ),
            _eps(
                value=8.0,
                effective_at="2025-09-27",
                available_at="2025-11-01T00:00:00+00:00",
            ),
            _eps(
                value=9999.0,
                effective_at="2026-09-26",
                available_at="2026-11-01T00:00:00+00:00",
            ),
        ]
    )
    market = _MarketService(_market_payload(instrument_id=instrument_id, price=200.0))

    result = RecommendationValuationSignalService(
        database=database,
        market_service=market,
    ).evaluate(symbol=" aapl ", as_of=AS_OF)

    assert result.status == "diagnostic_ready"
    assert result.instrument_id == instrument_id
    assert result.entity_id == "sec-cik:0000320193"
    assert result.latest_price == pytest.approx(200.0)
    assert result.annual_diluted_eps is not None
    assert result.annual_diluted_eps.value == pytest.approx(8.0)
    assert result.annual_diluted_eps.source_version is not None
    assert result.annual_diluted_eps.source_version.startswith("10-K|")
    assert result.reported_annual_pe == pytest.approx(25.0)
    assert result.market_source_providers == ("yahoo_finance",)
    assert result.production_eligible is False
    assert 9999.0 != result.annual_diluted_eps.value
    assert market.calls == [{"symbol": "AAPL", "as_of": AS_OF}]


def test_valuation_does_not_use_quarterly_eps_as_annual_multiple(tmp_path: Path) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    NormalizedDataRepository(database).save(
        _eps(
            value=2.0,
            effective_at="2025-12-27",
            available_at="2025-12-31T00:00:00+00:00",
            form="10-Q",
        )
    )

    result = RecommendationValuationSignalService(
        database=database,
        market_service=_MarketService(_market_payload(instrument_id=instrument_id)),
    ).evaluate(symbol="AAPL", as_of=AS_OF)

    assert result.status == "valuation_input_missing"
    assert result.annual_diluted_eps is None
    assert result.reported_annual_pe is None
    assert result.production_eligible is False


def test_valuation_does_not_force_pe_for_negative_earnings(tmp_path: Path) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    NormalizedDataRepository(database).save(
        _eps(
            value=-4.0,
            effective_at="2025-09-27",
            available_at="2025-11-01T00:00:00+00:00",
        )
    )

    result = RecommendationValuationSignalService(
        database=database,
        market_service=_MarketService(_market_payload(instrument_id=instrument_id)),
    ).evaluate(symbol="AAPL", as_of=AS_OF)

    assert result.status == "negative_or_zero_earnings"
    assert result.annual_diluted_eps is not None
    assert result.reported_annual_pe is None
    assert result.production_eligible is False


def test_valuation_blocks_when_market_evidence_is_not_ready(tmp_path: Path) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    market = _MarketService(
        _market_payload(status="insufficient_history", instrument_id=instrument_id)
    )

    result = RecommendationValuationSignalService(
        database=database,
        market_service=market,
    ).evaluate(symbol="AAPL", as_of=AS_OF)

    assert result.status == "market_evidence_not_ready"
    assert result.reported_annual_pe is None
    assert result.production_eligible is False


def test_valuation_fails_closed_if_market_component_claims_production(tmp_path: Path) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    service = RecommendationValuationSignalService(
        database=database,
        market_service=_MarketService(
            _market_payload(
                instrument_id=instrument_id,
                production_eligible=True,
            )
        ),
    )

    with pytest.raises(RuntimeError, match="productivo"):
        service.evaluate(symbol="AAPL", as_of=AS_OF)


def test_valuation_rejects_naive_as_of_before_market_call(tmp_path: Path) -> None:
    database, instrument_id = _database_with_identity(tmp_path)
    market = _MarketService(_market_payload(instrument_id=instrument_id))
    service = RecommendationValuationSignalService(
        database=database,
        market_service=market,
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=datetime(2026, 1, 1),
        )

    assert market.calls == []

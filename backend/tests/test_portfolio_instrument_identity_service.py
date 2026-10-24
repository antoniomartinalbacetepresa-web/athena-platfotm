import pytest

from app.services.portfolio_instrument_identity_service import (
    PortfolioInstrumentIdentityService,
)


class FakeInstrumentRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_active(self):
        return list(self.rows)


def row(
    *,
    database_id=1,
    symbol="AAPL",
    exchange="NASDAQ",
    exchange_short_name="NASDAQ",
    canonical_id="AAPL@NASDAQ",
    issuer_id="issuer:apple",
    currency="USD",
):
    return {
        "id": database_id,
        "symbol": symbol,
        "company_name": "Apple Inc.",
        "issuer_id": issuer_id,
        "instrument_id": canonical_id,
        "country": "United States",
        "exchange": exchange,
        "exchange_short_name": exchange_short_name,
        "instrument_type": "common_stock",
        "sector": "Technology",
        "currency": currency,
        "source_provider": "yahoo_catalog",
        "retrieved_at": "2026-09-04T18:00:00+00:00",
        "is_active": 1,
    }


def test_portfolio_identity_resolves_exact_listing_and_is_risk_ready() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([row()])
    )

    result = service.resolve(symbol="aapl", exchange="nasdaq")

    assert result.database_instrument_id == 1
    assert result.canonical_instrument_id == "AAPL@NASDAQ"
    assert result.issuer_id == "issuer:apple"
    assert result.exchange_verified is True
    assert result.is_risk_ready is True
    payload = result.to_api_dict()
    assert payload["isWeightingReady"] is False
    assert payload["recommendationPolicy"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_portfolio_identity_accepts_unique_symbol_but_exposes_exchange_mismatch() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([row()])
    )

    result = service.resolve(symbol="AAPL", exchange="NMS")

    assert result.resolution_method == "unique_active_symbol"
    assert result.exchange_verified is False
    assert result.is_risk_ready is False


def test_portfolio_identity_unique_symbol_without_exchange_stays_risk_blocked() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([row()])
    )

    result = service.resolve(symbol="AAPL", exchange=None)

    assert result.resolution_method == "unique_active_symbol"
    assert result.exchange_verified is False
    assert result.is_risk_ready is False


def test_portfolio_identity_fails_closed_for_ambiguous_symbol() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository(
            [
                row(database_id=1, exchange="NASDAQ", exchange_short_name="NASDAQ"),
                row(
                    database_id=2,
                    exchange="XETRA",
                    exchange_short_name="XETRA",
                    canonical_id="AAPL@XETRA",
                ),
            ]
        )
    )

    with pytest.raises(ValueError, match="múltiples listings"):
        service.resolve(symbol="AAPL", exchange="NMS")


def test_portfolio_identity_uses_exact_exchange_to_disambiguate() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository(
            [
                row(database_id=1, exchange="NASDAQ", exchange_short_name="NASDAQ"),
                row(
                    database_id=2,
                    exchange="XETRA",
                    exchange_short_name="XETRA",
                    canonical_id="AAPL@XETRA",
                ),
            ]
        )
    )

    result = service.resolve(symbol="AAPL", exchange="XETRA")

    assert result.database_instrument_id == 2
    assert result.canonical_instrument_id == "AAPL@XETRA"
    assert result.exchange_verified is True


def test_portfolio_identity_requires_canonical_fields_and_iso_currency() -> None:
    missing_identity = row(canonical_id="")
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([missing_identity])
    )
    with pytest.raises(ValueError, match="instrument_id"):
        service.resolve(symbol="AAPL", exchange="NASDAQ")

    invalid_currency = row(currency="US")
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([invalid_currency])
    )
    with pytest.raises(ValueError, match="moneda canónica"):
        service.resolve(symbol="AAPL", exchange="NASDAQ")


def test_portfolio_identity_rejects_unknown_symbol() -> None:
    service = PortfolioInstrumentIdentityService(
        repository=FakeInstrumentRepository([row()])
    )

    with pytest.raises(ValueError, match="no existe"):
        service.resolve(symbol="MSFT", exchange="NASDAQ")

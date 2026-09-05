from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_valuation_evidence_service import (
    RecommendationPortfolioValuationEvidenceService,
)


AS_OF = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


class _InstrumentRepository:
    def get_by_id(self, instrument_id):
        if instrument_id != 1:
            return None
        return {
            "id": 1,
            "instrument_id": "canonical-aapl-xnas",
            "issuer_id": 10,
            "symbol": "AAPL",
            "exchange_short_name": "XNAS",
            "instrument_type": "equity",
            "country": "US",
            "currency": "USD",
            "sector": "Technology",
        }


class _MarketRepository:
    def __init__(self, *, retrieved_at="2026-09-05T11:00:00+00:00", close=200.0):
        self.retrieved_at = retrieved_at
        self.close = close

    def list_for_instrument(
        self,
        instrument_id,
        *,
        source_provider=None,
        knowledge_cutoff=None,
        observed_from=None,
        observed_to=None,
    ):
        assert source_provider == "yahoo"
        assert knowledge_cutoff == AS_OF
        return [
            {
                "instrument_id": instrument_id,
                "source_provider": "yahoo",
                "observed_at": "2026-09-05T10:00:00+00:00",
                "retrieved_at": self.retrieved_at,
                "close": self.close,
            }
        ]


class _FxService:
    def __init__(self, *, rate=0.85, retrieved_at="2026-09-05T11:30:00+00:00"):
        self.rate = rate
        self.retrieved_at = retrieved_at

    def get_historical_rate(
        self,
        *,
        base_currency,
        quote_currency,
        observed_on,
        knowledge_cutoff=None,
    ):
        assert base_currency == "USD"
        assert quote_currency == "EUR"
        assert knowledge_cutoff == AS_OF
        return {
            "status": "fx_historical_ready",
            "baseCurrency": "USD",
            "quoteCurrency": "EUR",
            "rate": self.rate,
            "observedOn": observed_on.isoformat(),
            "observedAt": "2026-09-05T00:00:00+00:00",
            "retrievedAt": self.retrieved_at,
            "sourceProvider": "yahoo",
            "sourceSymbol": "USDEUR=X",
            "historicalPointInTimeEligible": True,
            "replayedFromPersistence": True,
        }


def _position():
    return {
        "instrumentId": 1,
        "quantity": 2.0,
        "positionSourceProvider": "user_portfolio_input",
        "positionObservedAt": "2026-09-05T09:00:00+00:00",
        "positionRetrievedAt": "2026-09-05T09:01:00+00:00",
        "marketSourceProvider": "yahoo",
    }


def _service(*, market=None, fx=None):
    return RecommendationPortfolioValuationEvidenceService(
        instrument_repository=_InstrumentRepository(),
        market_repository=market or _MarketRepository(),
        fx_service=fx or _FxService(),
    )


def test_builds_canonical_pit_fx_bound_valuation_without_claiming_cash_or_advice():
    service = _service()

    result = service.build(
        positions=[_position()],
        base_currency="EUR",
        as_of=AS_OF,
    )

    assert result["portfolioValuationEvidenceReady"] is True
    assert result["investedPositionsValueInBaseCurrency"] == pytest.approx(340.0)
    assert result["cashIncluded"] is False
    assert result["liabilitiesIncluded"] is False
    assert result["valuationScope"] == (
        "invested_long_positions_only_cash_liabilities_unsettled_excluded"
    )
    position = result["positions"][0]
    assert position["canonicalIdentity"]["canonicalInstrumentId"] == "canonical-aapl-xnas"
    assert position["priceSourceProvider"] == "yahoo"
    assert position["fx"]["sourceSymbol"] == "USDEUR=X"
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False
    assert service.validate_artifact(result) is result


def test_duplicate_instrument_fails_closed():
    with pytest.raises(ValueError, match="duplicado"):
        _service().build(
            positions=[_position(), _position()],
            base_currency="EUR",
            as_of=AS_OF,
        )


def test_position_known_after_as_of_fails_closed():
    position = _position()
    position["positionRetrievedAt"] = "2026-09-05T12:00:01+00:00"
    with pytest.raises(ValueError, match="después de as_of"):
        _service().build(positions=[position], base_currency="EUR", as_of=AS_OF)


def test_market_observation_known_after_as_of_fails_closed_even_if_repository_leaks_it():
    with pytest.raises(ValueError, match="corte temporal"):
        _service(market=_MarketRepository(retrieved_at="2026-09-05T12:00:01+00:00")).build(
            positions=[_position()],
            base_currency="EUR",
            as_of=AS_OF,
        )


def test_fx_known_after_as_of_fails_closed():
    with pytest.raises(ValueError, match="corte PIT"):
        _service(fx=_FxService(retrieved_at="2026-09-05T12:00:01+00:00")).build(
            positions=[_position()],
            base_currency="EUR",
            as_of=AS_OF,
        )


def test_non_finite_price_and_fx_fail_closed():
    with pytest.raises(ValueError, match="market.close"):
        _service(market=_MarketRepository(close=float("nan"))).build(
            positions=[_position()], base_currency="EUR", as_of=AS_OF
        )
    with pytest.raises(ValueError, match="fx.rate"):
        _service(fx=_FxService(rate=float("inf"))).build(
            positions=[_position()], base_currency="EUR", as_of=AS_OF
        )


def test_tampered_artifact_fingerprint_fails_closed():
    service = _service()
    result = service.build(positions=[_position()], base_currency="EUR", as_of=AS_OF)
    tampered = deepcopy(result)
    tampered["positions"][0]["quantity"] = 999.0

    with pytest.raises(ValueError, match="modificada"):
        service.validate_artifact(tampered)

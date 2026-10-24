"""PIT and no-order boundaries for observed dividend total return.

Research-only examples; no live data, provider calls or trading.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.dividend_total_return_service import DividendTotalReturnService


CUTOFF = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def _calculate(**overrides):
    kwargs = dict(
        start_price=100.0,
        end_price=103.0,
        dividend_cash_per_share=2.0,
        currency="EUR",
        source_provider="issuer_filing",
        knowledge_cutoff=CUTOFF,
    )
    kwargs.update(overrides)
    return DividendTotalReturnService().calculate(**kwargs)


def test_pit_requires_each_observation_timestamp():
    valid = CUTOFF - timedelta(hours=1)
    for missing in ("start_observed_at", "end_observed_at", "dividend_observed_at"):
        timestamps = dict.fromkeys(("start_observed_at", "end_observed_at", "dividend_observed_at"), valid)
        timestamps[missing] = None
        result = _calculate(**timestamps)
        assert result.pit_safe is False
        assert result.to_api_dict()["productionEligible"] is False


def test_pit_timestamps_do_not_grant_production_or_trading_authority():
    result = _calculate(
        start_observed_at=CUTOFF - timedelta(days=2),
        end_observed_at=CUTOFF - timedelta(days=1),
        dividend_observed_at=CUTOFF - timedelta(hours=1),
    )
    payload = result.to_api_dict()
    assert result.pit_safe is True
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False
    assert payload["dividendsReinvested"] is False
    assert payload["totalReturn"] == pytest.approx(0.05)
    assert payload["priceReturn"] == pytest.approx(0.03)
    assert payload["dividendReturn"] == pytest.approx(0.02)


@pytest.mark.parametrize("field", ["start_observed_at", "end_observed_at", "dividend_observed_at"])
def test_future_observation_relative_to_cutoff_is_rejected(field):
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        _calculate(**{field: CUTOFF + timedelta(microseconds=1)})


@pytest.mark.parametrize("field", ["start_observed_at", "end_observed_at", "dividend_observed_at"])
def test_naive_observation_is_rejected(field):
    with pytest.raises(ValueError, match="zona horaria"):
        _calculate(**{field: datetime(2026, 10, 12, 10)})


def test_start_observation_cannot_follow_end_observation():
    with pytest.raises(ValueError, match="posterior"):
        _calculate(
            start_observed_at=CUTOFF - timedelta(hours=1),
            end_observed_at=CUTOFF - timedelta(hours=2),
        )


def test_cutoff_cannot_be_in_the_future():
    with pytest.raises(ValueError, match="fecha futura"):
        _calculate(knowledge_cutoff=datetime.now(timezone.utc) + timedelta(days=1))


@pytest.mark.parametrize("field,value", [
    ("start_price", 0.0), ("start_price", -1.0),
    ("end_price", -0.01), ("dividend_cash_per_share", -0.01),
])
def test_invalid_price_or_cash_bounds_are_rejected(field, value):
    with pytest.raises(ValueError):
        _calculate(**{field: value})


@pytest.mark.parametrize("currency", ["€UR", "EU", "EURO", "US1", "US D", ""])
def test_currency_must_be_three_ascii_letters(currency):
    with pytest.raises(ValueError, match="currency"):
        _calculate(currency=currency)


def test_component_provenance_does_not_merge_into_single_source():
    result = _calculate(
        price_source_provider="exchange_history",
        dividend_source_provider="issuer_filing",
    )
    assert result.price_source_provider == "exchange_history"
    assert result.dividend_source_provider == "issuer_filing"
    assert result.source_provider == "issuer_filing"
    assert result.to_api_dict()["productionEligible"] is False

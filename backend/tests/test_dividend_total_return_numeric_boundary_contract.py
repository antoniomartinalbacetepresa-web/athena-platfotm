"""Financial numeric, timezone and research-only boundaries for dividend total return.

These deterministic tests do not assert live coverage or production readiness.
"""
from datetime import datetime, timedelta, timezone
import math

import pytest

from app.services.dividend_total_return_service import DividendTotalReturnService


CUTOFF = datetime(2024, 6, 1, tzinfo=timezone.utc)


def calculate(**overrides):
    args = dict(
        start_price=100.0,
        end_price=101.0,
        dividend_cash_per_share=2.0,
        currency="eur",
        source_provider="issuer_filing",
        knowledge_cutoff=CUTOFF,
        start_observed_at=CUTOFF - timedelta(days=4),
        end_observed_at=CUTOFF - timedelta(days=2),
        dividend_observed_at=CUTOFF - timedelta(days=1),
    )
    args.update(overrides)
    return DividendTotalReturnService().calculate(**args)


@pytest.mark.parametrize("field", ["start_price", "end_price", "dividend_cash_per_share"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, "12.5"])
def test_invalid_observation_never_enters_financial_calculation(field, invalid):
    with pytest.raises(ValueError, match="finitos"):
        calculate(**{field: invalid})


def test_non_reinvested_total_return_is_exact_component_sum():
    result = calculate(start_price=80, end_price=72, dividend_cash_per_share=4)
    assert result.price_return == pytest.approx(-0.1)
    assert result.dividend_return == pytest.approx(0.05)
    assert result.total_return == pytest.approx(-0.05)
    assert result.total_return == pytest.approx(result.price_return + result.dividend_return)
    assert result.to_api_dict()["dividendsReinvested"] is False


def test_timezone_offsets_are_normalized_to_utc_for_pit():
    offset = timezone(timedelta(hours=2))
    result = calculate(
        knowledge_cutoff=datetime(2024, 6, 1, 2, tzinfo=offset),
        start_observed_at=datetime(2024, 5, 28, 2, tzinfo=offset),
        end_observed_at=datetime(2024, 5, 30, 2, tzinfo=offset),
        dividend_observed_at=datetime(2024, 5, 31, 2, tzinfo=offset),
    )
    assert result.knowledge_cutoff == "2024-06-01T00:00:00+00:00"
    assert result.pit_safe is True
    assert result.to_api_dict()["productionEligible"] is False
    assert result.to_api_dict()["automaticTrading"] is False


def test_same_instant_different_offsets_do_not_trigger_false_pit_ordering():
    plus_two = timezone(timedelta(hours=2))
    result = calculate(
        start_observed_at=datetime(2024, 5, 30, 2, tzinfo=plus_two),
        end_observed_at=datetime(2024, 5, 30, 0, tzinfo=timezone.utc),
    )
    assert result.pit_safe is True
    assert result.start_observed_at == result.end_observed_at


def test_zero_end_price_is_permitted_but_never_grants_trading_authority():
    result = calculate(end_price=0, dividend_cash_per_share=0)
    assert result.total_return == -1
    assert result.to_api_dict()["automaticTrading"] is False


def test_extreme_ratio_overflow_is_rejected_instead_of_serialized():
    with pytest.raises(ValueError, match="finitos"):
        calculate(start_price=1e-300, end_price=1e300)


def test_currency_normalization_is_ascii_only():
    assert calculate(currency=" usd ").currency == "USD"
    with pytest.raises(ValueError, match="currency"):
        calculate(currency="𝖀𝕾𝕯")


def test_mixed_sources_remain_separate_and_never_claim_production():
    result = calculate(
        source_provider="issuer_filing",
        price_source_provider="yahoo_finance",
        dividend_source_provider="exchange_disclosure",
    )
    payload = result.to_api_dict()
    assert payload["priceSourceProvider"] == "yahoo_finance"
    assert payload["dividendSourceProvider"] == "exchange_disclosure"
    assert payload["sourceProvider"] == "issuer_filing"
    assert payload["pitSafe"] is True
    assert payload["productionEligible"] is False

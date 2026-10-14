"""Encoded FMP must never be accepted as observed dividend provenance."""
from datetime import datetime, timedelta, timezone
import pytest
from app.services.dividend_total_return_service import DividendTotalReturnService

CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)

def _calculate(**changes):
    values = dict(start_price=100.0, end_price=105.0, dividend_cash_per_share=2.0,
                  currency="EUR", source_provider="issuer_filing", knowledge_cutoff=CUTOFF,
                  start_observed_at=CUTOFF - timedelta(days=3),
                  end_observed_at=CUTOFF - timedelta(days=2),
                  dividend_observed_at=CUTOFF - timedelta(days=1))
    values.update(changes)
    return DividendTotalReturnService().calculate(**values)

@pytest.mark.parametrize("field", ("source_provider", "price_source_provider", "dividend_source_provider"))
@pytest.mark.parametrize("alias", ("&#70;&#77;&#80;", "&#x46;&#x4d;&#x50;", "&amp;#70;&amp;#77;&amp;#80;",
    "%26%2370%3B%26%2377%3B%26%2380%3B", "&#70&#77&#80"))
def test_reject_html_encoded_fmp(field, alias):
    with pytest.raises(ValueError, match="FMP"):
        _calculate(**{field: alias})

def test_pit_and_no_trading_unchanged():
    result = _calculate()
    assert result.total_return == pytest.approx(0.07)
    assert result.pit_safe is True
    assert result.to_api_dict()["automaticTrading"] is False
    assert result.to_api_dict()["productionEligible"] is False

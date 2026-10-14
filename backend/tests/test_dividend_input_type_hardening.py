"""Reject malformed observations before financial return arithmetic."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.dividend_total_return_service import DividendTotalReturnService


BASE = dict(
    start_price=100.0,
    end_price=105.0,
    dividend_cash_per_share=2.0,
    currency="EUR",
    source_provider="issuer-filing",
    knowledge_cutoff=datetime(2026, 10, 11, tzinfo=timezone.utc),
)


@pytest.mark.parametrize("field", ["start_price", "end_price", "dividend_cash_per_share"])
@pytest.mark.parametrize("bad", [True, False, "100", "nan", None, 10**1000])
def test_malformed_amounts_are_rejected_as_contract_errors(field, bad):
    with pytest.raises(ValueError, match="finitos"):
        DividendTotalReturnService().calculate(**{**BASE, field: bad})


def test_decimal_amounts_remain_supported():
    result = DividendTotalReturnService().calculate(
        **{**BASE, "start_price": Decimal("100"), "end_price": Decimal("105")}
    )
    assert result.total_return == pytest.approx(0.07)


@pytest.mark.parametrize("field", ["source_provider", "price_source_provider", "dividend_source_provider"])
@pytest.mark.parametrize("blocked", [
    "FMP", "mirror-fmp", "F.M.P.", "ＦＭＰ", "Financial Modeling Prep",
    "secondary_financialmodelingprep",
])
def test_fmp_cannot_be_hidden_in_component_provenance(field, blocked):
    with pytest.raises(ValueError, match="FMP"):
        DividendTotalReturnService().calculate(**{**BASE, field: blocked})


@pytest.mark.parametrize("provider", ["Yahoo Finance", "Google Finance", "Alpha Vantage"])
def test_allowed_provider_names_remain_supported(provider):
    result = DividendTotalReturnService().calculate(**{**BASE, "source_provider": provider})
    assert result.source_provider == provider
    assert result.to_api_dict()["productionEligible"] is False

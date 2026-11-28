"""PIT fundamentals must reject nested HTML/URL-encoded FMP provenance."""
from datetime import datetime, timedelta, timezone
import pytest
from app.services.portfolio_dividend_return_evidence_service import (
    DividendFundamentalEvidence, PortfolioDividendReturnEvidenceService,
)
CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)

def _fundamentals(**changes):
    values = dict(price=100.0, trailing_dividend_per_share=2.0,
                  payout_ratio=0.5, fcf_payout_ratio=0.6,
                  available_at=CUTOFF - timedelta(days=1),
                  source="issuer_filing", source_ref="filing-2026")
    values.update(changes)
    return PortfolioDividendReturnEvidenceService._fundamentals(
        DividendFundamentalEvidence(**values), as_of=CUTOFF)

@pytest.mark.parametrize("field", ("source", "source_ref"))
@pytest.mark.parametrize("alias", ("&#70;&#77;&#80;", "&#x46;&#x4d;&#x50;",
    "&amp;#70;&amp;#77;&amp;#80;", "%26%2370%3B%26%2377%3B%26%2380%3B"))
def test_fmp_aliases_rejected(field, alias):
    with pytest.raises(ValueError, match="FMP"):
        _fundamentals(**{field: alias})

def test_legitimate_pit_evidence_preserved():
    price, dps, payout, fcf, status, refs = _fundamentals()
    assert (price, dps, payout, fcf) == (100.0, 2.0, 0.5, 0.6)
    assert status == "supported"
    assert refs == ("issuer_filing:filing-2026",)

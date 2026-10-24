"""PIT dividend fundamentals: type and provenance fail-closed contract.

These tests exercise the real Portfolio service (not a copied snippet).
No external market provider, network, trading, or live investment data.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.portfolio_dividend_return_evidence_service import (
    DividendFundamentalEvidence,
    PortfolioDividendReturnEvidenceService,
)

CUTOFF = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def _evidence(**changes):
    values = {
        "price": 100.0,
        "trailing_dividend_per_share": 2.5,
        "payout_ratio": 0.5,
        "fcf_payout_ratio": 0.6,
        "available_at": CUTOFF,
        "source": "issuer_filing",
        "source_ref": "filing-2026-001",
    }
    values.update(changes)
    return DividendFundamentalEvidence(**values)


def _fundamentals(evidence):
    return PortfolioDividendReturnEvidenceService._fundamentals(
        evidence, as_of=CUTOFF
    )


@pytest.mark.parametrize("field", [
    "price", "trailing_dividend_per_share", "payout_ratio", "fcf_payout_ratio",
])
@pytest.mark.parametrize("invalid", [
    True, False, "100", "nan", float("nan"), float("inf"), float("-inf"),
    10 ** 1000, object(),
])
def test_fundamental_fields_reject_invalid_types_and_nonfinite(field, invalid):
    with pytest.raises(ValueError, match="numeric and finite"):
        _fundamentals(_evidence(**{field: invalid}))


@pytest.mark.parametrize("field", ["source", "source_ref"])
@pytest.mark.parametrize("invalid", [
    None, "", "  ", True, 123, object(),
])
def test_provenance_requires_nonblank_strings(field, invalid):
    with pytest.raises(ValueError, match="explicit provenance"):
        _fundamentals(_evidence(**{field: invalid}))


@pytest.mark.parametrize("field", ["source", "source_ref"])
@pytest.mark.parametrize("blocked", [
    "FMP", "f.m.p", "financialmodelingprep", "Financial Modeling Prep",
    "ＦＭＰ", "%46%4d%50", "%2546%254d%2550",
    "https://financialmodelingprep.com/api/v3/quote",
    "https%3A%2F%2Ffinancialmodelingprep.com%2Fapi",
])
def test_provider_and_reference_reject_fmp_even_when_encoded(field, blocked):
    with pytest.raises(ValueError, match="FMP"):
        _fundamentals(_evidence(**{field: blocked}))


def test_excessively_nested_provenance_encoding_fails_closed():
    encoded = "FMP"
    for _ in range(9):
        encoded = "".join(f"%{ord(ch):02X}" for ch in encoded)
    with pytest.raises(ValueError, match="FMP|ambiguous"):
        _fundamentals(_evidence(source_ref=encoded))


@pytest.mark.parametrize("field,value", [
    ("price", 0), ("price", -1),
    ("trailing_dividend_per_share", -0.01),
])
def test_price_and_dividend_amount_bounds(field, value):
    with pytest.raises(ValueError):
        _fundamentals(_evidence(**{field: value}))


def test_pit_future_information_is_rejected():
    with pytest.raises(ValueError, match="PIT-available"):
        _fundamentals(_evidence(available_at=CUTOFF + timedelta(seconds=1)))


def test_approved_source_and_numeric_values_keep_dimensions():
    price, dps, payout, fcf, sustainability, refs = _fundamentals(_evidence())
    assert (price, dps, payout, fcf) == (100.0, 2.5, 0.5, 0.6)
    assert sustainability == "supported"
    assert refs == ("issuer_filing:filing-2026-001",)


def test_no_inferred_fundamentals_without_observation():
    assert _fundamentals(None) == (
        None, None, None, None, "insufficient_evidence", ()
    )

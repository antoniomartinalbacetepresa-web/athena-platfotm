"""Real service contract: no concealed FMP provider in total-return evidence."""
from datetime import datetime, timedelta, timezone
import pytest
from app.services.dividend_total_return_service import DividendTotalReturnService


def calculate(**overrides):
    values = {
        'start_price': 100.0,
        'end_price': 101.0,
        'dividend_cash_per_share': 2.0,
        'currency': 'USD',
        'source_provider': 'issuer_filing',
        'knowledge_cutoff': datetime.now(timezone.utc) - timedelta(days=1),
    }
    values.update(overrides)
    return DividendTotalReturnService().calculate(**values)


@pytest.mark.parametrize('field', ['source_provider', 'price_source_provider', 'dividend_source_provider'])
@pytest.mark.parametrize('alias', [
    'FMP', 'financialmodelingprep', 'Financial Modeling Prep', 'ＦＭＰ',
    '%46%4d%50', '%2546%254d%2550',
    'https%3A%2F%2Ffinancialmodelingprep.com%2Fapi',
])
def test_disguised_provider_rejected(field, alias):
    with pytest.raises(ValueError, match='FMP'):
        calculate(**{field: alias})


@pytest.mark.parametrize('field', ['source_provider', 'price_source_provider', 'dividend_source_provider'])
def test_ambiguous_nested_encoding_rejected(field):
    alias = 'FMP'
    for _ in range(9):
        alias = ''.join(f'%{ord(character):02X}' for character in alias)
    with pytest.raises(ValueError, match='FMP|ambigua'):
        calculate(**{field: alias})


def test_independent_providers_preserve_separate_provenance():
    result = calculate(source_provider='issuer_filing',
                       price_source_provider='yahoo_finance',
                       dividend_source_provider='exchange_disclosure')
    assert result.source_provider == 'issuer_filing'
    assert result.price_source_provider == 'yahoo_finance'
    assert result.dividend_source_provider == 'exchange_disclosure'
    assert result.total_return == pytest.approx(0.03)
    assert result.pit_safe is False
    assert result.to_api_dict()['automaticTrading'] is False

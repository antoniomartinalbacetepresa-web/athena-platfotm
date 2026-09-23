from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_dividend_total_return_binding_service import RecommendationDividendTotalReturnBindingService


CUTOFF = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _bind(**overrides):
    values = dict(
        start_price=100.0,
        end_price=108.0,
        dividend_cash_per_share=3.0,
        currency="USD",
        price_source_provider="market_history",
        dividend_source_provider="issuer_filing",
        price_observed_at=CUTOFF - timedelta(minutes=30),
        price_retrieved_at=CUTOFF - timedelta(minutes=20),
        dividend_retrieved_at=CUTOFF - timedelta(days=1),
        knowledge_cutoff=CUTOFF,
    )
    values.update(overrides)
    return RecommendationDividendTotalReturnBindingService().bind(**values).to_api_dict()


def test_binding_preserves_component_provenance_and_total_return() -> None:
    payload = _bind()
    total_return = payload["totalReturn"]
    assert total_return["priceReturn"] == pytest.approx(0.08)
    assert total_return["dividendReturn"] == pytest.approx(0.03)
    assert total_return["totalReturn"] == pytest.approx(0.11)
    assert total_return["sourceProvider"] == "mixed"
    assert total_return["priceSourceProvider"] == "market_history"
    assert total_return["dividendSourceProvider"] == "issuer_filing"
    assert total_return["knowledgeCutoff"] == CUTOFF.isoformat()
    assert total_return["pitSafe"] is True
    assert total_return["dividendsReinvested"] is False
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_binding_rejects_future_component_evidence() -> None:
    with pytest.raises(ValueError, match="posterior al knowledge_cutoff"):
        _bind(dividend_retrieved_at=CUTOFF + timedelta(seconds=1))


def test_binding_rejects_missing_component_provenance() -> None:
    with pytest.raises(ValueError, match="price_source_provider"):
        _bind(price_source_provider=" ")
    with pytest.raises(ValueError, match="dividend_source_provider"):
        _bind(dividend_source_provider=" ")

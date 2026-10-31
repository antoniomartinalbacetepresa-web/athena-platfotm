"""Regression coverage for total-return PIT evidence and fail-closed authority."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.dividend_total_return_service import DividendTotalReturnService


CUTOFF = datetime(2026, 10, 11, 18, tzinfo=timezone.utc)
OBSERVED = CUTOFF - timedelta(days=1)


def _calculate(**overrides):
    args = dict(
        start_price=100.0,
        end_price=105.0,
        dividend_cash_per_share=2.0,
        currency="EUR",
        source_provider="issuer-filing",
        knowledge_cutoff=CUTOFF,
    )
    args.update(overrides)
    return DividendTotalReturnService().calculate(**args).to_api_dict()


@pytest.mark.parametrize("present", [(), ("start_observed_at",), ("start_observed_at", "end_observed_at")])
def test_incomplete_component_evidence_never_claims_pit_safe(present):
    result = _calculate(**{key: OBSERVED for key in present})
    assert result["pitSafe"] is False
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_complete_evidence_marks_only_structural_pit_not_production():
    result = _calculate(start_observed_at=OBSERVED, end_observed_at=OBSERVED, dividend_observed_at=OBSERVED)
    assert result["pitSafe"] is True
    assert result["startObservedAt"] == OBSERVED.isoformat()
    assert result["endObservedAt"] == OBSERVED.isoformat()
    assert result["dividendObservedAt"] == OBSERVED.isoformat()
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


@pytest.mark.parametrize("field", ["start_observed_at", "end_observed_at", "dividend_observed_at"])
def test_observation_after_cutoff_is_rejected(field):
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        _calculate(**{field: CUTOFF + timedelta(seconds=1)})


@pytest.mark.parametrize("field", ["start_observed_at", "end_observed_at", "dividend_observed_at"])
def test_naive_observation_is_rejected(field):
    with pytest.raises(ValueError, match="zona horaria"):
        _calculate(**{field: datetime(2026, 10, 10)})


def test_start_observation_after_end_observation_is_rejected():
    with pytest.raises(ValueError, match="start_observed_at.*posterior.*end_observed_at"):
        _calculate(start_observed_at=OBSERVED + timedelta(hours=1),
                   end_observed_at=OBSERVED, dividend_observed_at=OBSERVED)


def test_timezone_normalization_keeps_pit_causality():
    plus_two = timezone(timedelta(hours=2))
    result = _calculate(start_observed_at=OBSERVED.astimezone(plus_two),
                        end_observed_at=OBSERVED, dividend_observed_at=OBSERVED)
    assert result["pitSafe"] is True
    assert result["startObservedAt"] == OBSERVED.isoformat()


def test_zero_cash_still_requires_evidence_of_absence():
    assert _calculate(dividend_cash_per_share=0.0)["pitSafe"] is False


@pytest.mark.parametrize("field", ["source_provider", "price_source_provider", "dividend_source_provider"])
def test_fmp_is_rejected_for_every_component(field):
    with pytest.raises(ValueError, match="FMP"):
        _calculate(**{field: "financial-modeling-prep"})


@pytest.mark.parametrize("currency", ["", "US", "EURO", "€UR", "USD1"])
def test_invalid_currency_is_rejected(currency):
    with pytest.raises(ValueError, match="currency"):
        _calculate(currency=currency)


def test_future_cutoff_is_rejected():
    with pytest.raises(ValueError, match="futura"):
        _calculate(knowledge_cutoff=datetime.now(timezone.utc) + timedelta(days=1))

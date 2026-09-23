from datetime import datetime, timezone

import pytest

from app.services.dividend_total_return_service import DividendTotalReturnService


def test_total_return_includes_observed_dividend_cash_and_provenance() -> None:
    result = DividendTotalReturnService().calculate(
        start_price=100.0,
        end_price=108.0,
        dividend_cash_per_share=3.0,
        currency="usd",
        source_provider="issuer-filing",
        knowledge_cutoff=datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
    )

    assert result.price_return == pytest.approx(0.08)
    assert result.dividend_return == pytest.approx(0.03)
    assert result.total_return == pytest.approx(0.11)
    payload = result.to_api_dict()
    assert payload["currency"] == "USD"
    assert payload["sourceProvider"] == "issuer-filing"
    assert payload["priceSourceProvider"] == "issuer-filing"
    assert payload["dividendSourceProvider"] == "issuer-filing"
    assert payload["pitSafe"] is True
    assert payload["dividendsReinvested"] is False
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_total_return_preserves_distinct_price_and_dividend_provenance() -> None:
    payload = DividendTotalReturnService().calculate(
        start_price=100.0,
        end_price=105.0,
        dividend_cash_per_share=2.0,
        currency="EUR",
        source_provider="composite-observed-return",
        price_source_provider="market-history-primary",
        dividend_source_provider="issuer-filing",
        knowledge_cutoff=datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
    ).to_api_dict()

    assert payload["priceSourceProvider"] == "market-history-primary"
    assert payload["dividendSourceProvider"] == "issuer-filing"
    assert payload["totalReturn"] == pytest.approx(0.07)
    assert payload["pitSafe"] is True
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_price", float("nan")),
        ("end_price", float("inf")),
        ("dividend_cash_per_share", float("-inf")),
    ],
)
def test_total_return_rejects_non_finite_inputs(field: str, value: float) -> None:
    kwargs = {
        "start_price": 100.0,
        "end_price": 108.0,
        "dividend_cash_per_share": 3.0,
        "currency": "EUR",
        "source_provider": "verified-source",
        "knowledge_cutoff": datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        DividendTotalReturnService().calculate(**kwargs)


def test_total_return_requires_provenance_and_timezone_aware_cutoff() -> None:
    service = DividendTotalReturnService()
    with pytest.raises(ValueError):
        service.calculate(
            start_price=100.0,
            end_price=100.0,
            dividend_cash_per_share=1.0,
            currency="EUR",
            source_provider=" ",
            knowledge_cutoff=datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError):
        service.calculate(
            start_price=100.0,
            end_price=100.0,
            dividend_cash_per_share=1.0,
            currency="EUR",
            source_provider="verified-source",
            knowledge_cutoff=datetime(2026, 9, 23, 9, 0),
        )


@pytest.mark.parametrize("field", ["price_source_provider", "dividend_source_provider"])
def test_total_return_rejects_blank_component_provenance(field: str) -> None:
    kwargs = {
        "start_price": 100.0,
        "end_price": 101.0,
        "dividend_cash_per_share": 1.0,
        "currency": "USD",
        "source_provider": "composite",
        "knowledge_cutoff": datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
        field: " ",
    }
    with pytest.raises(ValueError):
        DividendTotalReturnService().calculate(**kwargs)

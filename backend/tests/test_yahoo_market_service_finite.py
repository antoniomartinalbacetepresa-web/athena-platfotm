import pytest

from app.services.yahoo_market_service import YahooMarketService


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, False],
)
def test_yahoo_market_service_rejects_non_finite_and_boolean_numbers(value) -> None:
    service = YahooMarketService()

    assert service._to_float(value) is None


def test_yahoo_market_service_accepts_finite_numeric_values() -> None:
    service = YahooMarketService()

    assert service._to_float("123.45") == pytest.approx(123.45)
    assert service._to_float(-1.5) == pytest.approx(-1.5)

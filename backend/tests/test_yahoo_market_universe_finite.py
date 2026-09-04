import pytest

from app.services.yahoo_market_universe_service import YahooMarketUniverseService


class FakeFxService:
    def __init__(self, value):
        self.value = value

    def convert_to_usd(self, *, amount, currency):
        return self.value


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, False, 0.0, -1.0],
)
def test_yahoo_market_universe_rejects_invalid_market_caps(value) -> None:
    service = YahooMarketUniverseService()

    assert service._to_positive_float(value) is None


@pytest.mark.parametrize(
    "fx_result",
    [float("nan"), float("inf"), float("-inf"), True, False, 0.0, -1.0],
)
def test_yahoo_market_universe_rejects_invalid_fx_conversion(fx_result) -> None:
    service = YahooMarketUniverseService(fx_service=FakeFxService(fx_result))

    assert (
        service._convert_market_cap_to_usd(
            market_cap_local=100.0,
            currency="EUR",
        )
        is None
    )


def test_yahoo_market_universe_accepts_finite_positive_values() -> None:
    service = YahooMarketUniverseService(fx_service=FakeFxService(125.0))

    assert service._to_positive_float("100.5") == pytest.approx(100.5)
    assert service._convert_market_cap_to_usd(
        market_cap_local=100.0,
        currency="EUR",
    ) == pytest.approx(125.0)

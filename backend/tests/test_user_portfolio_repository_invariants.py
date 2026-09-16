from __future__ import annotations

import math

import pytest

from app.repositories.user_portfolio_repository import UserPortfolioRepository


@pytest.mark.parametrize(
    "quantity",
    [float("nan"), float("inf"), float("-inf")],
)
def test_quantity_rejects_non_finite_values(quantity: float) -> None:
    with pytest.raises(ValueError, match="finito"):
        UserPortfolioRepository._quantity(quantity)


def test_quantity_keeps_existing_positive_operational_boundaries() -> None:
    assert UserPortfolioRepository._quantity(0.000001) == pytest.approx(0.000001)
    assert UserPortfolioRepository._quantity(1_000_000_000_000) == pytest.approx(
        1_000_000_000_000
    )

    with pytest.raises(ValueError, match="límite operativo"):
        UserPortfolioRepository._quantity(0.0)
    with pytest.raises(ValueError, match="límite operativo"):
        UserPortfolioRepository._quantity(1_000_000_000_000.01)


def test_quantity_returns_only_finite_float_for_valid_input() -> None:
    quantity = UserPortfolioRepository._quantity(12)

    assert isinstance(quantity, float)
    assert quantity == 12.0
    assert math.isfinite(quantity)

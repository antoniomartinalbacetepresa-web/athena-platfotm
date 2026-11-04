from datetime import datetime, timedelta, timezone

import pytest

from app.services.opportunity_exit_pattern_service import DailyBar, observe_pattern


def sample_bars():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        DailyBar(
            observed_at=start + timedelta(days=i),
            available_at=start + timedelta(days=i, hours=1),
            close=100.0 if i < 20 else 110.0,
            volume=1000.0 if i < 20 else 2000.0,
        )
        for i in range(21)
    ]


def test_observation_is_descriptive_and_never_advisory():
    bars = sample_bars()
    result = observe_pattern(
        bars, as_of=bars[-1].available_at,
        licensed=True, corporate_actions_verified=True,
    )
    assert result.trend == "above_20d_reference"
    assert result.volume_confirmation == "above_recent_average"
    assert result.advisory_status == "no_advice"
    assert result.automatic_trading is False
    assert result.close_vs_20d_mean_pct > 0
    assert result.warnings


@pytest.mark.parametrize("licensed,adjusted", [(False, True), (True, False)])
def test_rejects_unverified_sources(licensed, adjusted):
    bars = sample_bars()
    with pytest.raises(ValueError):
        observe_pattern(
            bars, as_of=bars[-1].available_at,
            licensed=licensed, corporate_actions_verified=adjusted,
        )


def test_rejects_future_availability_and_unsorted_bars():
    bars = sample_bars()
    with pytest.raises(ValueError):
        observe_pattern(
            bars, as_of=bars[-1].observed_at,
            licensed=True, corporate_actions_verified=True,
        )
    with pytest.raises(ValueError):
        observe_pattern(
            list(reversed(bars)), as_of=bars[-1].available_at,
            licensed=True, corporate_actions_verified=True,
        )


def test_rejects_nonfinite_prices_and_short_series():
    bars = sample_bars()
    with pytest.raises(ValueError):
        observe_pattern(
            bars[:20], as_of=bars[-1].available_at,
            licensed=True, corporate_actions_verified=True,
        )
    invalid = bars.copy()
    invalid[-1] = DailyBar(
        observed_at=bars[-1].observed_at,
        available_at=bars[-1].available_at,
        close=float("nan"),
        volume=100,
    )
    with pytest.raises(ValueError):
        observe_pattern(
            invalid, as_of=bars[-1].available_at,
            licensed=True, corporate_actions_verified=True,
        )

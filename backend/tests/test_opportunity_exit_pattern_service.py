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


def test_reference_uses_exactly_twenty_prior_sessions_not_nineteen():
    bars = sample_bars()
    # One low observation at the beginning of the 20-session reference
    # distinguishes a correct 20-prior-session mean from a 19-session mean.
    bars[0] = DailyBar(
        observed_at=bars[0].observed_at,
        available_at=bars[0].available_at,
        close=50.0,
        volume=1000.0,
    )
    result = observe_pattern(
        bars, as_of=bars[-1].available_at,
        licensed=True, corporate_actions_verified=True,
    )
    assert result.close_vs_20d_mean_pct == pytest.approx(12.8205, abs=0.0001)
    assert result.trend == "above_20d_reference"


def test_current_session_volume_is_not_in_its_own_reference():
    bars = sample_bars()
    # 20 prior sessions at 1000, current session at 1500: strictly
    # above 1.5x is required, not equal to the threshold.
    bars[-1] = DailyBar(
        observed_at=bars[-1].observed_at,
        available_at=bars[-1].available_at,
        close=bars[-1].close,
        volume=1500.0,
    )
    result = observe_pattern(
        bars, as_of=bars[-1].available_at,
        licensed=True, corporate_actions_verified=True,
    )
    assert result.volume_confirmation == "not_confirmed"

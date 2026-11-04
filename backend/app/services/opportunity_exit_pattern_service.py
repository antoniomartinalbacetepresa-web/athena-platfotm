"""Research-only price/volume pattern observations; no orders or advice.

Inputs must be independently licensed, PIT-eligible, split-adjusted and sorted.
This module deliberately refuses to infer data provenance or trading suitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import mean


@dataclass(frozen=True)
class DailyBar:
    observed_at: datetime
    available_at: datetime
    close: float
    volume: float


@dataclass(frozen=True)
class PatternObservation:
    as_of: datetime
    trend: str
    volume_confirmation: str
    close_vs_20d_mean_pct: float
    breakout_vs_prior_20d_high: bool
    drawdown_from_prior_20d_high_pct: float
    warnings: tuple[str, ...]
    advisory_status: str = "no_advice"
    automatic_trading: bool = False


def observe_pattern(
    bars: list[DailyBar], *, as_of: datetime,
    licensed: bool, corporate_actions_verified: bool,
) -> PatternObservation:
    """Describe an observable 20-session pattern without a buy/sell signal.

    Never silently treats a fixture, unlicensed price or unadjusted split as
    decision-grade evidence. No future-available observations are permitted.
    """
    if not licensed or not corporate_actions_verified:
        raise ValueError("Source licence and corporate actions require verification")
    if as_of.tzinfo is None or as_of.utcoffset() != timezone.utc.utcoffset(as_of):
        raise ValueError("as_of must be timezone-aware UTC")
    if len(bars) < 21:
        raise ValueError("At least 21 daily bars are required")
    previous = None
    previous_day = None
    for bar in bars:
        if bar.observed_at.tzinfo is None or bar.available_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if bar.observed_at.utcoffset() != timezone.utc.utcoffset(as_of):
            raise ValueError("Observation must use UTC")
        if bar.available_at.utcoffset() != timezone.utc.utcoffset(as_of):
            raise ValueError("Availability must use UTC")
        if bar.available_at < bar.observed_at or bar.available_at > as_of:
            raise ValueError("Future or unavailable observations are forbidden")
        if previous is not None and bar.observed_at <= previous:
            raise ValueError("Bars must be strictly ordered")
        if previous_day == bar.observed_at.date():
            raise ValueError("Daily series cannot contain multiple bars for one UTC day")
        if not isfinite(bar.close) or bar.close <= 0 or not isfinite(bar.volume) or bar.volume < 0:
            raise ValueError("Non-finite, negative or zero price/volume")
        previous = bar.observed_at
        previous_day = bar.observed_at.date()
    previous_20 = bars[-21:-1]
    latest = bars[-1]
    # The reference must contain exactly 20 *prior* observations; the
    # current session must not influence its own breakout baseline.
    baseline = mean(bar.close for bar in previous_20)
    change_pct = (latest.close / baseline - 1.0) * 100.0
    prior_high = max(bar.close for bar in previous_20)
    drawdown_pct = min(0.0, (latest.close / prior_high - 1.0) * 100.0)
    avg_volume = mean(bar.volume for bar in previous_20)
    confirmation = (
        "above_recent_average" if avg_volume > 0 and latest.volume > avg_volume * 1.5
        else "not_confirmed"
    )
    return PatternObservation(
        as_of=as_of,
        trend="above_20d_reference" if change_pct > 0 else "at_or_below_20d_reference",
        volume_confirmation=confirmation,
        close_vs_20d_mean_pct=round(change_pct, 4),
        breakout_vs_prior_20d_high=latest.close > prior_high,
        drawdown_from_prior_20d_high_pct=round(drawdown_pct, 4),
        warnings=(
            "Descriptive only; not a trade signal or validated forecast.",
            "Spreads, fees, slippage, liquidity and out-of-sample performance not assessed.",
        ),
    )

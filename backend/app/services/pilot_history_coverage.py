"""Fail-closed calendar coverage diagnostics for pilot market history.

Does not establish provider licensing, exchange-session completeness or production readiness.
"""
from datetime import datetime, timedelta, timezone

from .pilot_observation_contract import UnverifiedMarketObservation, validate_pilot_observation


def assess_pilot_history(bars: list[dict], *, as_of: datetime, min_days: int = 365) -> dict:
    if not isinstance(min_days, int) or isinstance(min_days, bool) or min_days < 1:
        raise UnverifiedMarketObservation("invalid minimum coverage")
    if not isinstance(bars, list) or not bars:
        raise UnverifiedMarketObservation("missing pilot history")
    verified = [validate_pilot_observation(bar, as_of=as_of) for bar in bars]
    identities = {(b["instrument_id"], b["currency"], b["adjustment_status"]) for b in verified}
    if len(identities) != 1:
        raise UnverifiedMarketObservation("mixed instrument, currency or adjustment basis")
    dates = [datetime.fromisoformat(b["observation_at"].replace("Z", "+00:00")).astimezone(timezone.utc).date() for b in verified]
    if dates != sorted(set(dates)):
        raise UnverifiedMarketObservation("duplicate or unordered observation dates")
    gaps = []
    for before, after in zip(dates, dates[1:]):
        missing = (after - before).days - 1
        if missing > 0:
            gaps.append({"from": (before + timedelta(days=1)).isoformat(),
                         "to": (after - timedelta(days=1)).isoformat(), "calendar_days": missing})
    span = (dates[-1] - dates[0]).days + 1
    return {"instrument_id": verified[0]["instrument_id"], "calendar_days_spanned": span,
            "observed_days": len(dates), "calendar_gaps": gaps,
            "minimum_span_met": span >= min_days, "production_coverage_claimed": False}

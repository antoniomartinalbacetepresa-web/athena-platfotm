"""Fail-closed provenance gate for pilot daily price observations.

This module validates metadata; it never fetches prices, grants data rights,
creates investment signals, or claims production readiness.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class EvidenceRejected(ValueError):
    """The observation cannot be used as verified PIT research evidence."""


def validate_daily_price_evidence(record: dict, *, as_of: datetime) -> dict:
    """Return a validated copy; reject absent rights, timestamps or adjustments.

    The provider must explicitly attest permission for this application's use.
    Corporate-action adjustment status must be explicit, even when unadjusted.
    """
    if not isinstance(record, dict) or not isinstance(as_of, datetime):
        raise EvidenceRejected("invalid input")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise EvidenceRejected("as_of must be timezone-aware")
    required = ("instrumentId", "symbol", "source", "licenseId",
                "usageAuthorized", "observationAt", "availableAt",
                "retrievedAt", "currency", "adjustmentPolicy", "close")
    if any(key not in record or record[key] is None for key in required):
        raise EvidenceRejected("incomplete provenance contract")
    if record["usageAuthorized"] is not True:
        raise EvidenceRejected("data usage not authorized")
    for key in ("instrumentId", "symbol", "source", "licenseId",
                "currency", "adjustmentPolicy"):
        if (not isinstance(record[key], str) or not record[key].strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in record[key])):
            raise EvidenceRejected(f"invalid {key}")
    if record["adjustmentPolicy"] not in ("raw", "split_adjusted", "total_return"):
        raise EvidenceRejected("unknown corporate action adjustment")
    times = []
    for key in ("observationAt", "availableAt", "retrievedAt"):
        value = record[key]
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise EvidenceRejected(f"invalid {key}")
        times.append(value.astimezone(timezone.utc))
    observation, available, retrieved = times
    if not (observation <= available <= retrieved <= as_of.astimezone(timezone.utc)):
        raise EvidenceRejected("PIT chronology invalid or future evidence")
    if isinstance(record["close"], bool):
        raise EvidenceRejected("invalid close")
    try:
        close = Decimal(str(record["close"]))
    except (InvalidOperation, ValueError, TypeError):
        raise EvidenceRejected("invalid close") from None
    if not close.is_finite() or close <= 0:
        raise EvidenceRejected("close must be positive and finite")
    if "volume" in record:
        volume = record["volume"]
        if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
            raise EvidenceRejected("volume must be a nonnegative integer")
        if record.get("volumeUnit") != "shares":
            raise EvidenceRejected("volumeUnit must be shares")
    elif "volumeUnit" in record:
        raise EvidenceRejected("volumeUnit without volume")
    return dict(record)


def summarize_daily_price_coverage(records: list[dict], *, as_of: datetime,
                                   required_days: int = 365) -> dict:
    """Report observed calendar coverage without inventing missing sessions.

    Every observation passes the same authorization/PIT gate. Calendar gaps
    are diagnostics, NOT proof that a market session or trade is missing.
    """
    if not isinstance(records, list) or not isinstance(required_days, int) or isinstance(required_days, bool) or required_days < 1:
        raise EvidenceRejected("invalid coverage input")
    validated = [validate_daily_price_evidence(item, as_of=as_of) for item in records]
    if not validated:
        return {"observations": 0, "calendarSpanDays": 0,
                "requiredDays": required_days, "depthSatisfied": False,
                "calendarGaps": [], "sessionCoverageVerified": False,
                "latestObservationAgeDays": None, "freshnessVerified": False}
    identities = {(item["instrumentId"], item["source"], item["currency"],
                   item["adjustmentPolicy"], item["licenseId"]) for item in validated}
    if len(identities) != 1:
        raise EvidenceRejected("mixed instrument or provenance in price series")
    ordered = sorted(validated, key=lambda item: item["observationAt"])
    dates = [item["observationAt"].astimezone(timezone.utc).date() for item in ordered]
    if len(set(dates)) != len(dates):
        raise EvidenceRejected("duplicate observation date")
    gaps = [{"after": left.isoformat(), "before": right.isoformat(),
             "calendarDaysBetween": (right - left).days - 1}
            for left, right in zip(dates, dates[1:])
            if (right - left).days > 1]
    span = (dates[-1] - dates[0]).days + 1
    return {"observations": len(ordered), "calendarSpanDays": span,
            "requiredDays": required_days, "depthSatisfied": span >= required_days,
            "calendarGaps": gaps, "sessionCoverageVerified": False,
            "latestObservationAgeDays": (as_of.astimezone(timezone.utc).date() - dates[-1]).days,
            "freshnessVerified": False}

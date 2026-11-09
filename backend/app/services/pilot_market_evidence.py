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
        if not isinstance(record[key], str) or not record[key].strip():
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
    try:
        close = Decimal(str(record["close"]))
    except (InvalidOperation, ValueError, TypeError):
        raise EvidenceRejected("invalid close") from None
    if not close.is_finite() or close <= 0:
        raise EvidenceRejected("close must be positive and finite")
    return dict(record)

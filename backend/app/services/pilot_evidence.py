"""Fail-closed metadata gate for a read-only pilot market observation.

This gate never licenses a feed: caller must verify provider rights independently.
"""
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping


class EvidenceRejected(ValueError):
    """Observation cannot be treated as verified research evidence."""


def validate_pilot_observation(record: Mapping[str, object], *, now: datetime, max_age_seconds: int | None = None) -> dict:
    """Return normalized provenance only for an authorized, PIT-safe observation.

    Freshness is measured from market observation, not later ingestion/availability.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise EvidenceRejected("now must be timezone-aware")
    required = ("instrumentId", "source", "licenseRef", "observationAt", "availableAt", "retrievedAt", "currency")
    if any(not isinstance(record.get(k), str) or not record[k].strip() for k in required):
        raise EvidenceRejected("missing provenance, identity, license reference or currency")
    if record.get("usageAuthorized") is not True:
        raise EvidenceRejected("provider usage rights not confirmed")
    timestamps = {}
    for key in ("observationAt", "availableAt", "retrievedAt"):
        try:
            stamp = datetime.fromisoformat(str(record[key]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceRejected(f"invalid {key}") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise EvidenceRejected(f"{key} lacks timezone")
        timestamps[key] = stamp.astimezone(timezone.utc)
    if not (timestamps["observationAt"] <= timestamps["availableAt"] <= timestamps["retrievedAt"] <= now):
        raise EvidenceRejected("observation, availability, retrieval and clock violate PIT ordering")
    exact_age_seconds = (now - timestamps["observationAt"]).total_seconds()
    age_seconds = int(exact_age_seconds)
    if max_age_seconds is not None:
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds < 0:
            raise EvidenceRejected("invalid maximum observation age")
        if exact_age_seconds > max_age_seconds:
            raise EvidenceRejected("observation exceeds permitted age")
    # A supplied market bar must never cross the research boundary with
    # NaN/Infinity, nonpositive prices, or negative fractional share volume.
    # Metadata-only callers remain supported until the shared bar contract lands.
    for field in ("open", "high", "low", "close"):
        if field in record:
            value = record[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise EvidenceRejected(f"invalid {field} price")
    present_prices = {field for field in ("open", "high", "low", "close") if field in record}
    if present_prices and present_prices != {"open", "high", "low", "close"}:
        raise EvidenceRejected("partial OHLC bar")
    if "volume" in record and not present_prices:
        raise EvidenceRejected("volume without OHLC bar")
    if "volume" in record:
        value = record["volume"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EvidenceRejected("invalid volume")
    if all(field in record for field in ("open", "high", "low", "close")):
        if record["low"] > min(record["open"], record["close"]) or record["high"] < max(record["open"], record["close"]) or record["low"] > record["high"]:
            raise EvidenceRejected("inconsistent OHLC bar")
    if record.get("isFinalBar") is not True:
        raise EvidenceRejected("incomplete or unconfirmed bar")
    # Preserve the validated bar for downstream API/persistence consumers.
    # Dropping these values would make the gate unusable as a data contract.
    return {**{k: record[k] for k in required if k not in timestamps},
            **{k: record[k] for k in ("open", "high", "low", "close", "volume") if k in record},
            **{k: v.isoformat() for k, v in timestamps.items()},
            "usageAuthorized": True, "isFinalBar": True,
            "ageSeconds": age_seconds}

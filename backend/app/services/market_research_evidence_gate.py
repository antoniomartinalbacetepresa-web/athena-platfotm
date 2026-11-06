"""Fail-closed admission of external market evidence for research (not order execution).

This boundary does not grant a data licence or prove independent reconciliation.
Consumers must check the returned status before using evidence in analysis.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


REQUIRED = ("instrumentId", "source", "license", "observationAt", "availableAt", "retrievedAt", "currency")


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def assess_market_evidence(
    evidence: Mapping[str, Any], *, now: datetime, max_age: timedelta = timedelta(days=2), trusted_verification: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return explicit reasons; never infer a licence or market-data freshness."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if max_age <= timedelta(0):
        raise ValueError("max_age must be positive")
    reasons: list[str] = []
    for key in REQUIRED:
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            reasons.append(f"missing_{key}")
    timestamps = {key: _utc(evidence.get(key)) for key in ("observationAt", "availableAt", "retrievedAt")}
    if any(value is None for value in timestamps.values()):
        reasons.append("invalid_timestamps")
    else:
        observed, available, retrieved = (timestamps[k] for k in ("observationAt", "availableAt", "retrievedAt"))
        if observed > available or available > retrieved:
            reasons.append("invalid_pit_order")
        current = now.astimezone(timezone.utc)
        if observed > current or available > current:
            reasons.append("future_market_evidence")
        if retrieved > current:
            reasons.append("future_retrieval")
        if current - observed > max_age:
            reasons.append("stale_observation")
    currency = evidence.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
        reasons.append("invalid_currency")
    # Provider payload claims are not independent authorization.\n    verification = trusted_verification or {}\n    if verification.get("licenseVerified") is not True:
        reasons.append("license_unverified")
    if verification.get("sourceAttributionVerified") is not True:
        reasons.append("source_unverified")
    if verification.get("corporateActionsStatus") != "verified":
        reasons.append("corporate_actions_unverified")
    if verification.get("coverageStatus") != "verified":
        reasons.append("coverage_unverified")
    if verification.get("independentReconciliation") is not True:
        reasons.append("reconciliation_unverified")
    return {"accepted": not reasons, "reasons": reasons, "mode": "research_only", "orderExecutionAllowed": False}

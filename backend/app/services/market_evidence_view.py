"""Read-only projection of externally verified market evidence for API/UI consumers.

No network call, licence grant, price inference or order execution occurs here.
"""
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

from app.services.market_research_evidence_gate import assess_market_evidence


def market_evidence_view(
    evidence: Mapping[str, Any], *, now: datetime,
    trusted_verification: Mapping[str, Any] | None = None,
    max_age: timedelta = timedelta(days=2),
) -> dict[str, Any]:
    """Expose source, timestamps and a fail-closed display state.

    Price is intentionally withheld unless independent verification succeeds.
    """
    admission = assess_market_evidence(
        evidence, now=now, max_age=max_age,
        trusted_verification=trusted_verification,
    )
    observed = evidence.get("observationAt")
    age_seconds = None
    if isinstance(observed, str):
        try:
            timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
                delta = now.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)
                # A future observation is invalid, not a zero-second-old quote.
                if delta >= timedelta(0):
                    age_seconds = delta.total_seconds()
        except ValueError:
            pass
    result = {
        "instrumentId": evidence.get("instrumentId"),
        "source": evidence.get("source"),
        "license": evidence.get("license"),
        "observationAt": observed,
        "availableAt": evidence.get("availableAt"),
        "retrievedAt": evidence.get("retrievedAt"),
        "currency": evidence.get("currency"),
        "ageSeconds": age_seconds,
        # UI must not infer freshness from a missing age or a verified header.
        "stalenessStatus": (
            "unknown" if age_seconds is None
            else "stale" if age_seconds > max_age.total_seconds()
            else "fresh"
        ),
        # Display only independent verification, never provider self-attestation.
        "licenseVerified": admission["accepted"],
        "coverageStatus": "verified" if admission["accepted"] else "unverified",
        "corporateActionsStatus": "verified" if admission["accepted"] else "unverified",
        "independentReconciliation": admission["accepted"],
        "status": "verified_research" if admission["accepted"] else "unavailable_unverified",
        "reasons": admission["reasons"],
        "orderExecutionAllowed": False,
        "price": None,
        "priceStatus": "unavailable_unverified",
    }
    if admission["accepted"]:
        # The gate binds metadata, not the price. Never let a verified header
        # authorize a substituted or invalid numeric quote.
        price = evidence.get("price")
        verified_price = (trusted_verification or {}).get("price")
        # Huge Python integers overflow when converted by math.isfinite.
        # Fail closed instead of returning HTTP 500 to the Market consumer.
        def finite_positive(value: Any) -> bool:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                return isfinite(value) and value > 0
            except (OverflowError, ValueError, TypeError):
                return False

        valid = finite_positive(price) and finite_positive(verified_price) and verified_price == price
        if valid:
            result["price"] = price
            result["priceStatus"] = "verified"
        else:
            result["status"] = "unavailable_unverified"
            result["licenseVerified"] = False
            result["coverageStatus"] = "unverified"
            result["corporateActionsStatus"] = "unverified"
            result["independentReconciliation"] = False
            result["reasons"] = [*result["reasons"], "price_unverified"]
    return result

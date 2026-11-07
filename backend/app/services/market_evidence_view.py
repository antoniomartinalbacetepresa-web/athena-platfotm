"""Read-only projection of externally verified market evidence for API/UI consumers.

No network call, licence grant, price inference or order execution occurs here.
"""
from datetime import datetime, timedelta, timezone
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
                    age_seconds = int(delta.total_seconds())
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
        # Display only independent verification, never provider self-attestation.
        "licenseVerified": admission["accepted"],
        "coverageStatus": "verified" if admission["accepted"] else "unverified",
        "corporateActionsStatus": "verified" if admission["accepted"] else "unverified",
        "independentReconciliation": admission["accepted"],
        "status": "verified_research" if admission["accepted"] else "unavailable_unverified",
        "reasons": admission["reasons"],
        "orderExecutionAllowed": False,
        "price": None,
    }
    if admission["accepted"]:
        # The gate binds metadata, not the price. Never let a verified header
        # authorize a substituted or invalid numeric quote.
        price = evidence.get("price")
        verified_price = (trusted_verification or {}).get("price")
        from math import isfinite
        valid = (
            isinstance(price, (int, float)) and not isinstance(price, bool)
            and isfinite(price) and price > 0
            and isinstance(verified_price, (int, float))
            and not isinstance(verified_price, bool)
            and isfinite(verified_price) and verified_price == price
        )
        if valid:
            result["price"] = price
        else:
            result["status"] = "unavailable_unverified"
            result["licenseVerified"] = False
            result["coverageStatus"] = "unverified"
            result["corporateActionsStatus"] = "unverified"
            result["independentReconciliation"] = False
            result["reasons"] = [*result["reasons"], "price_unverified"]
    return result

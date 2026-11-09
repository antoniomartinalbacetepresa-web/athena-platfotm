"""Read-only pilot research payload; never infer provider authorization.

The upstream adapter must supply an independently reviewed usageAuthorized flag.
No network request, recommendation, or order is performed here.
"""
from datetime import datetime
from typing import Mapping

from app.services.pilot_evidence import EvidenceRejected, validate_pilot_observation


def build_pilot_market_view(
    observation: Mapping[str, object] | None,
    *,
    now: datetime,
    max_age_seconds: int = 86400 * 4,
    rights_reviewed: bool = False,
) -> dict:
    """Produce a UI-safe state without presenting rejected evidence as a quote."""
    # A feed must not authorize itself by setting usageAuthorized=True.
    # The caller must independently attest rights after a separate review.
    if rights_reviewed is not True:
        return {"status": "unavailable", "reason": "independent_rights_review_required", "observation": None}
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds < 0:
        return {"status": "unavailable", "reason": "invalid_freshness_policy", "observation": None}
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return {"status": "unavailable", "reason": "invalid_research_clock", "observation": None}
    if observation is None:
        return {"status": "unavailable", "reason": "no_authorized_observation", "observation": None}
    try:
        verified = validate_pilot_observation(
            observation, now=now, max_age_seconds=max_age_seconds, require_bar=True
        )
    except (EvidenceRejected, TypeError, AttributeError, ValueError, OverflowError):
        return {"status": "unavailable", "reason": "evidence_rejected", "observation": None}
    return {
        "status": "verified_metadata",
        "reason": "rights_attested_metadata_only_not_operationally_verified",
        "observation": verified,
        "researchOnly": True,
        "ordersEnabled": False,
    }

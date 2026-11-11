"""Read-only pilot history projection with explicit exchange-session gaps.

The exchange calendar and independent rights attestation are caller responsibilities.
No interpolation, network access, advice or order execution occurs here.
"""
from datetime import datetime
from typing import Mapping

from app.services.pilot_evidence import EvidenceRejected, validate_pilot_history


def build_pilot_history_view(
    observations: list[Mapping[str, object]],
    *,
    expected_sessions: list[str],
    now: datetime,
    rights_reviewed: bool = False,
    max_latest_age_seconds: int | None = None,
) -> dict:
    """Expose verified bars and coverage only after independent rights review."""
    unavailable = {"status": "unavailable", "history": None}
    if rights_reviewed is not True:
        return {**unavailable, "reason": "independent_rights_review_required"}
    if max_latest_age_seconds is not None and (\n        isinstance(max_latest_age_seconds, bool)\n        or not isinstance(max_latest_age_seconds, int)\n        or max_latest_age_seconds < 0\n    ):\n        return {**unavailable, "reason": "invalid_freshness_policy"}\n    try:\n        history = validate_pilot_history(
            observations, expected_sessions=expected_sessions, now=now
        )
    except (EvidenceRejected, TypeError, AttributeError, ValueError, OverflowError):
        return {**unavailable, "reason": "history_evidence_rejected"}
    # Historical coverage and recency are separate gates: an old but complete\n    # series must not be presented as a current research snapshot.\n    if (max_latest_age_seconds is not None\n            and history["latestAgeSeconds"] > max_latest_age_seconds):\n        return {**unavailable, "reason": "stale_history"}\n    return {\n        "status": "verified_metadata",
        "reason": "rights_attested_metadata_only_not_operationally_verified",
        "history": history,
        "coverageComplete": history["coverageComplete"],
        "missingSessions": history["missingSessions"],
        "researchOnly": True,
        "ordersEnabled": False,
    }

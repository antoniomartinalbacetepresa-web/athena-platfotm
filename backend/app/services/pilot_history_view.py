"""Read-only pilot history projection with explicit exchange-session gaps.

The exchange calendar and independent rights attestation are caller responsibilities.
No interpolation, network access, advice or order execution occurs here.
"""
from datetime import datetime, timezone
from typing import Mapping

from app.services.pilot_evidence import EvidenceRejected, validate_pilot_history


def build_pilot_history_view(
    observations: list[Mapping[str, object]],
    *,
    expected_sessions: list[str],
    now: datetime,
    rights_reviewed: bool = False,
    max_latest_age_seconds: int | None = None,
    expected_instrument_id: str | None = None,
) -> dict:
    """Expose verified bars and coverage only after independent rights review."""
    unavailable = {"status": "unavailable", "history": None}
    if rights_reviewed is not True:
        return {**unavailable, "reason": "independent_rights_review_required"}
    if max_latest_age_seconds is not None and (
        isinstance(max_latest_age_seconds, bool)
        or not isinstance(max_latest_age_seconds, int)
        or max_latest_age_seconds < 0
    ):
        return {**unavailable, "reason": "invalid_freshness_policy"}
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return {**unavailable, "reason": "invalid_research_clock"}
    if expected_instrument_id is not None and (
        not isinstance(expected_instrument_id, str)
        or not expected_instrument_id.strip()
        or expected_instrument_id != expected_instrument_id.strip()
    ):
        return {**unavailable, "reason": "invalid_instrument_selection"}
    try:
        history = validate_pilot_history(
            observations, expected_sessions=expected_sessions, now=now
        )
    except (EvidenceRejected, TypeError, AttributeError, ValueError, OverflowError):
        return {**unavailable, "reason": "history_evidence_rejected"}
    if expected_instrument_id is not None and history["instrumentId"] != expected_instrument_id:
        return {**unavailable, "reason": "instrument_mismatch"}
    # Historical coverage and recency are separate gates: an old but complete
    # series must not be presented as a current research snapshot.
    # The public age is rounded down for display; enforce freshness with the
    # exact timestamp so a bar 0.9 seconds too old cannot pass the gate.
    latest_at = datetime.fromisoformat(history["latestObservationAt"])
    exact_age = (now.astimezone(timezone.utc) - latest_at.astimezone(timezone.utc)).total_seconds()
    if (max_latest_age_seconds is not None
            and exact_age > max_latest_age_seconds):
        return {**unavailable, "reason": "stale_history"}
    # A recency limit cannot make a missing latest expected session current.
    # The exchange calendar is still caller-supplied and not independently attested.
    if (max_latest_age_seconds is not None
            and history["expectedLastSession"] in history["missingSessions"]):
        return {**unavailable, "reason": "latest_expected_session_missing"}
    # A complete caller-supplied session list is not proof of a year of history.
    # Report calendar span separately so a one-session pilot cannot look like
    # 365-day coverage. This is metadata, never an operational coverage claim.
    first_day = datetime.fromisoformat(history["expectedFirstSession"]).date()
    last_day = datetime.fromisoformat(history["expectedLastSession"]).date()
    calendar_span_days = (last_day - first_day).days + 1
    # A sparse caller-supplied calendar must not manufacture annual equity depth.
    # This conservative pilot-equity guard is not an exchange-calendar attestation.
    sufficient_sessions = history["expectedSessionCount"] >= 200
    # Zero-volume final sessions may be valid but cannot support a liquidity
    # conclusion. Surface them explicitly rather than implying tradability.
    zero_volume_sessions = [bar["session"] for bar in history["bars"] if bar["volume"] == 0]
    return {
        "instrumentId": history["instrumentId"],
        "source": history["source"],
        "licenseRef": history["licenseRef"],
        "currency": history["currency"],
        "latestObservationAt": history["latestObservationAt"],
        "latestAvailableAt": history["bars"][-1]["availableAt"],
        "latestRetrievedAt": history["bars"][-1]["retrievedAt"],
        "latestAgeSeconds": history["latestAgeSeconds"],
        "calendarSpanDays": calendar_span_days,
        "sufficientAnnualSessions": sufficient_sessions,
        "meets365DayDepth": history["coverageComplete"] and calendar_span_days >= 365 and sufficient_sessions,
        "status": "verified_metadata",
        "reason": "rights_attested_metadata_only_not_operationally_verified",
        "history": history,
        # Completeness is relative to the caller-supplied calendar, not proof
        # that the calendar or provider license has been independently audited.
        "observedSessionCount": len(history["bars"]),
        "expectedSessionCount": history["expectedSessionCount"],
        "missingSessionCount": len(history["missingSessions"]),
        "coverageRatio": len(history["bars"]) / history["expectedSessionCount"],
        "coverageBasis": "caller_supplied_expected_sessions_not_exchange_attested",
        "coverageComplete": history["coverageComplete"],
        "missingSessions": history["missingSessions"],
        # A valid older bar does not establish coverage of the latest expected
        # exchange session. Keep this separate from timestamp freshness.
        "latestExpectedSession": history["expectedLastSession"],
        "latestExpectedSessionMissing": history["expectedLastSession"] in history["missingSessions"],
        "zeroVolumeSessions": zero_volume_sessions,
        "liquidityAssessmentAvailable": False,
        "researchOnly": True,
        "ordersEnabled": False,
    }

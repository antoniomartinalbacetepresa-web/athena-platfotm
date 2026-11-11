"""Fail-closed authorization gate for a pilot market/news observation.

This module never grants redistribution rights by inference. Authorization must
come from an independently reviewed provider agreement for the exact use.
"""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class PilotSourceEvidence:
    provider: str
    instrument_id: str
    license_reference: str
    permitted_use: str
    observation_at: datetime
    available_at: datetime
    retrieved_at: datetime
    reviewed: bool = False


def usable_for_research(
    evidence: PilotSourceEvidence, *, now: datetime, max_age_seconds: int | None = None
) -> bool:
    """Require explicit reviewed rights and causally ordered UTC timestamps."""
    if max_age_seconds is not None and (
        isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int)
        or max_age_seconds < 0
    ):
        return False
    if not isinstance(evidence, PilotSourceEvidence) or not isinstance(now, datetime):
        return False
    if not all(isinstance(value, str) for value in (
        evidence.provider, evidence.instrument_id, evidence.license_reference,
        evidence.permitted_use,
    )):
        return False
    timestamps = (
        evidence.observation_at,
        evidence.available_at,
        evidence.retrieved_at,
        now,
    )
    if any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None for value in timestamps):
        return False
    if not all((evidence.provider.strip(), evidence.instrument_id.strip(),
                evidence.license_reference.strip())):
        return False
    if evidence.permitted_use != "internal_research" or evidence.reviewed is not True:
        return False
    observation, available, retrieved, current = (
        value.astimezone(timezone.utc) for value in timestamps
    )
    if not observation <= available <= retrieved <= current:
        return False
    return max_age_seconds is None or (current - observation).total_seconds() <= max_age_seconds


def usable_history_for_research(
    observations: list[PilotSourceEvidence], *, now: datetime,
    max_age_seconds: int, minimum_observations: int = 2,
    minimum_span_days: int | None = None,
) -> bool:
    """Reject partial or mixed-rights pilot histories before analytical use.

    This is a metadata gate, not proof of 365-day coverage, price adjustment,
    licensing, or a production-ready source. Those require separate evidence.
    """
    if (not isinstance(observations, list)
        or isinstance(minimum_observations, bool)
        or not isinstance(minimum_observations, int)
        or minimum_observations < 2
        or len(observations) < minimum_observations
        or (minimum_span_days is not None and (
            isinstance(minimum_span_days, bool)
            or not isinstance(minimum_span_days, int)
            or minimum_span_days < 1))):
        return False
    if not all(usable_for_research(item, now=now) for item in observations):
        return False
    first = observations[0]
    identity = (first.provider, first.instrument_id, first.license_reference,
                first.permitted_use)
    if any((item.provider, item.instrument_id, item.license_reference,
            item.permitted_use) != identity for item in observations[1:]):
        return False
    if any(left.observation_at >= right.observation_at
           for left, right in zip(observations, observations[1:])):
        return False
    if minimum_span_days is not None and (
        observations[-1].observation_at - observations[0].observation_at
    ).total_seconds() < minimum_span_days * 86400:
        return False
    return usable_for_research(observations[-1], now=now,
                               max_age_seconds=max_age_seconds)

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

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


def usable_for_research(evidence: PilotSourceEvidence, *, now: datetime) -> bool:
    """Require explicit reviewed rights and causally ordered UTC timestamps."""
    timestamps = (
        evidence.observation_at,
        evidence.available_at,
        evidence.retrieved_at,
        now,
    )
    if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
        return False
    if not all((evidence.provider.strip(), evidence.instrument_id.strip(),
                evidence.license_reference.strip())):
        return False
    if evidence.permitted_use != "internal_research" or not evidence.reviewed:
        return False
    observation, available, retrieved, current = (
        value.astimezone(timezone.utc) for value in timestamps
    )
    return observation <= available <= retrieved <= current

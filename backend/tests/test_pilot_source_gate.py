from datetime import datetime, timedelta, timezone

from app.services.pilot_source_gate import PilotSourceEvidence, usable_for_research


NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def evidence(**changes):
    values = dict(
        provider="approved-provider",
        instrument_id="US5949181045",
        license_reference="reviewed-agreement-1",
        permitted_use="internal_research",
        observation_at=NOW - timedelta(days=2),
        available_at=NOW - timedelta(days=1),
        retrieved_at=NOW - timedelta(hours=1),
        reviewed=True,
    )
    values.update(changes)
    return PilotSourceEvidence(**values)


def test_reviewed_internal_research_is_eligible():
    assert usable_for_research(evidence(), now=NOW)


def test_unreviewed_or_unlicensed_never_eligible():
    assert not usable_for_research(evidence(reviewed=False), now=NOW)
    assert not usable_for_research(evidence(license_reference=" "), now=NOW)
    assert not usable_for_research(evidence(permitted_use="redistribution"), now=NOW)


def test_future_or_lookahead_observations_are_rejected():
    assert not usable_for_research(evidence(available_at=NOW + timedelta(seconds=1)), now=NOW)
    assert not usable_for_research(evidence(retrieved_at=NOW + timedelta(seconds=1)), now=NOW)
    assert not usable_for_research(evidence(observation_at=NOW), now=NOW)


def test_naive_clock_fails_closed():
    assert not usable_for_research(evidence(), now=NOW.replace(tzinfo=None))
    assert not usable_for_research(
        evidence(available_at=NOW.replace(tzinfo=None)), now=NOW
    )

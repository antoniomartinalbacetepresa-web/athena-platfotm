from datetime import datetime, timedelta, timezone

from app.services.pilot_source_gate import PilotSourceEvidence, usable_for_research, usable_history_for_research


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


def test_observation_age_is_measured_from_market_time_not_retrieval():
    # A recent download cannot refresh an old price observation.
    assert not usable_for_research(evidence(), now=NOW, max_age_seconds=86400)
    assert usable_for_research(evidence(), now=NOW, max_age_seconds=172800)
    assert not usable_for_research(evidence(), now=NOW, max_age_seconds=0)


def test_invalid_freshness_policy_fails_closed():
    for invalid in (-1, True, 1.5, "86400"):
        assert not usable_for_research(evidence(), now=NOW, max_age_seconds=invalid)


def test_malformed_provider_metadata_and_clock_fail_closed():
    for bad in (
        {"provider": None},
        {"instrument_id": 42},
        {"license_reference": None},
        {"permitted_use": None},
        {"observation_at": "2026-11-08T00:00:00Z"},
        {"available_at": None},
        {"retrieved_at": 0},
        {"reviewed": 1},
    ):
        assert usable_for_research(evidence(**bad), now=NOW) is False
    for bad_now in (None, "2026-11-09T12:00:00Z", 0):
        assert usable_for_research(evidence(), now=bad_now) is False
    assert usable_for_research(None, now=NOW) is False


def test_pilot_history_requires_consistent_rights_order_and_fresh_latest_bar():
    older = evidence(observation_at=NOW - timedelta(days=3),
                     available_at=NOW - timedelta(days=2),
                     retrieved_at=NOW - timedelta(hours=2))
    latest = evidence(observation_at=NOW - timedelta(hours=2),
                      available_at=NOW - timedelta(hours=1),
                      retrieved_at=NOW - timedelta(minutes=30))
    assert usable_history_for_research([older, latest], now=NOW,
                                       max_age_seconds=10800)
    assert not usable_history_for_research([older], now=NOW,
                                           max_age_seconds=10800)
    assert not usable_history_for_research([latest, older], now=NOW,
                                           max_age_seconds=10800)
    assert not usable_history_for_research([older, latest, latest], now=NOW,
                                           max_age_seconds=10800)
    assert not usable_history_for_research(
        [older, evidence(provider="different-provider",
                         observation_at=latest.observation_at,
                         available_at=latest.available_at,
                         retrieved_at=latest.retrieved_at)],
        now=NOW, max_age_seconds=10800)
    assert not usable_history_for_research(
        [older, evidence(license_reference="different-rights",
                         observation_at=latest.observation_at,
                         available_at=latest.available_at,
                         retrieved_at=latest.retrieved_at)],
        now=NOW, max_age_seconds=10800)
    assert not usable_history_for_research([older, latest], now=NOW,
                                           max_age_seconds=3600)
    assert not usable_history_for_research([older, latest], now=NOW,
                                           max_age_seconds=10800,
                                           minimum_observations=True)

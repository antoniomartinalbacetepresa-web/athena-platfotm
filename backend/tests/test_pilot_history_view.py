from datetime import datetime, timezone

from app.services.pilot_history_view import build_pilot_history_view

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
BAR = {
    "instrumentId": "MSFT", "source": "test-only",
    "licenseRef": "test-only-not-a-license", "usageAuthorized": True,
    "observationAt": "2026-11-06T21:00:00Z",
    "availableAt": "2026-11-06T21:01:00Z",
    "retrievedAt": "2026-11-07T08:00:00Z",
    "currency": "USD", "isFinalBar": True,
    "open": 10.0, "high": 11.0, "low": 9.0,
    "close": 10.5, "volume": 1000,
}


def test_rights_must_be_independently_attested_before_bars_are_exposed():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW
    )
    assert result == {
        "status": "unavailable",
        "history": None,
        "reason": "independent_rights_review_required",
    }


def test_history_exposes_missing_exchange_sessions_without_interpolation():
    result = build_pilot_history_view(
        [BAR],
        expected_sessions=["2026-11-05", "2026-11-06"],
        now=NOW,
        rights_reviewed=True,
    )
    assert result["status"] == "verified_metadata"
    assert result["coverageComplete"] is False
    assert result["missingSessions"] == ["2026-11-05"]
    assert len(result["history"]["bars"]) == 1
    assert result["history"]["operationallyVerified"] is False
    assert result["researchOnly"] is True
    assert result["ordersEnabled"] is False


def test_future_pit_or_inconsistent_history_never_leaks_quotes():
    for bar in (
        {**BAR, "availableAt": "2026-11-09T00:00:00Z"},
        {**BAR, "high": 9.0},
    ):
        result = build_pilot_history_view(
            [bar], expected_sessions=["2026-11-06"],
            now=NOW, rights_reviewed=True,
        )
        assert result == {
            "status": "unavailable",
            "history": None,
            "reason": "history_evidence_rejected",
        }


def test_freshness_policy_distinguishes_stale_history_from_complete_coverage():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, max_latest_age_seconds=3600,
    )
    assert result == {"status": "unavailable", "history": None, "reason": "stale_history"}
    fresh = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, max_latest_age_seconds=86400 * 3,
    )
    assert fresh["status"] == "verified_metadata"
    assert fresh["coverageComplete"] is True
    assert fresh["history"]["operationallyVerified"] is False


def test_invalid_history_freshness_policy_fails_closed():
    for value in (-1, True, 1.5, "86400"):
        result = build_pilot_history_view(
            [BAR], expected_sessions=["2026-11-06"], now=NOW,
            rights_reviewed=True, max_latest_age_seconds=value,
        )
        assert result == {
            "status": "unavailable", "history": None,
            "reason": "invalid_freshness_policy",
        }


def test_freshness_gate_uses_fractional_seconds_not_display_age():
    from datetime import timedelta

    observed = datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)
    bar = {**BAR, "observationAt": observed.isoformat(),
           "availableAt": (observed + timedelta(seconds=1)).isoformat(),
           "retrievedAt": (observed + timedelta(seconds=2)).isoformat()}
    now = observed + timedelta(seconds=3600, milliseconds=500)
    result = build_pilot_history_view(
        [bar], expected_sessions=["2026-11-06"], now=now,
        rights_reviewed=True, max_latest_age_seconds=3600,
    )
    assert result == {"status": "unavailable", "history": None, "reason": "stale_history"}

    at_boundary = build_pilot_history_view(
        [bar], expected_sessions=["2026-11-06"],
        now=observed + timedelta(seconds=3600),
        rights_reviewed=True, max_latest_age_seconds=3600,
    )
    assert at_boundary["status"] == "verified_metadata"


def test_single_session_is_not_365_day_depth_even_when_coverage_complete():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True,
    )
    assert result["coverageComplete"] is True
    assert result["calendarSpanDays"] == 1
    assert result["meets365DayDepth"] is False


def test_missing_sessions_cannot_claim_365_day_depth():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2025-11-07", "2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert result["calendarSpanDays"] == 365
    assert result["coverageComplete"] is False
    assert result["meets365DayDepth"] is False


def test_invalid_or_naive_research_clock_fails_closed():
    for clock in (None, "2026-11-08T00:00:00Z", datetime(2026, 11, 8)):
        result = build_pilot_history_view(
            [BAR], expected_sessions=["2026-11-06"],
            now=clock, rights_reviewed=True,
        )
        assert result == {
            "status": "unavailable", "history": None,
            "reason": "invalid_research_clock",
        }


def test_sparse_calendar_cannot_claim_annual_equity_coverage():
    older = {**BAR, "observationAt": "2025-11-07T21:00:00Z",
             "availableAt": "2025-11-07T21:01:00Z",
             "retrievedAt": "2025-11-08T08:00:00Z"}
    result = build_pilot_history_view(
        [older, BAR], expected_sessions=["2025-11-07", "2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert result["coverageComplete"] is True
    assert result["calendarSpanDays"] == 365
    assert result["sufficientAnnualSessions"] is False
    assert result["meets365DayDepth"] is False


def test_history_projection_exposes_pit_and_provenance_without_inventing_verification():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True,
    )
    assert result["instrumentId"] == BAR["instrumentId"]
    assert result["source"] == BAR["source"]
    assert result["licenseRef"] == BAR["licenseRef"]
    assert result["currency"] == BAR["currency"]
    assert result["latestObservationAt"] == "2026-11-06T21:00:00+00:00"
    assert result["latestAvailableAt"] == "2026-11-06T21:01:00+00:00"
    assert result["latestRetrievedAt"] == "2026-11-07T08:00:00+00:00"
    assert result["latestAgeSeconds"] == 97200
    assert result["history"]["operationallyVerified"] is False
    assert result["status"] == "verified_metadata"


def test_zero_volume_final_session_is_visible_but_not_liquidity_evidence():
    result = build_pilot_history_view(
        [{**BAR, "volume": 0}], expected_sessions=["2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert result["status"] == "verified_metadata"
    assert result["zeroVolumeSessions"] == ["2026-11-06"]
    assert result["liquidityAssessmentAvailable"] is False
    assert result["ordersEnabled"] is False


def test_positive_volume_does_not_imply_executable_liquidity():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert result["zeroVolumeSessions"] == []
    assert result["liquidityAssessmentAvailable"] is False


def test_session_coverage_is_explicitly_scoped_to_unattested_calendar():
    partial = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-05", "2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert partial["observedSessionCount"] == 1
    assert partial["expectedSessionCount"] == 2
    assert partial["missingSessionCount"] == 1
    assert partial["coverageRatio"] == 0.5
    assert partial["coverageBasis"] == "caller_supplied_expected_sessions_not_exchange_attested"
    assert partial["meets365DayDepth"] is False

    complete = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert complete["coverageRatio"] == 1.0
    assert complete["meets365DayDepth"] is False
    assert complete["history"]["operationallyVerified"] is False


def test_missing_latest_expected_session_is_visible_separately_from_age():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06", "2026-11-07"],
        now=NOW, rights_reviewed=True,
    )
    assert result["status"] == "verified_metadata"
    assert result["latestExpectedSession"] == "2026-11-07"
    assert result["latestExpectedSessionMissing"] is True
    assert result["latestAgeSeconds"] == 97200
    assert result["coverageComplete"] is False

    complete = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"],
        now=NOW, rights_reviewed=True,
    )
    assert complete["latestExpectedSessionMissing"] is False


def test_selected_instrument_is_enforced_on_history_without_leaking_other_quotes():
    matched = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert matched["status"] == "verified_metadata"
    assert matched["instrumentId"] == "MSFT"

    mismatch = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="AAPL",
    )
    assert mismatch == {
        "status": "unavailable", "history": None, "reason": "instrument_mismatch",
    }

    for selection in ("", " MSFT", "MSFT ", 0, True):
        invalid = build_pilot_history_view(
            [BAR], expected_sessions=["2026-11-06"], now=NOW,
            rights_reviewed=True, expected_instrument_id=selection,
        )
        assert invalid == {
            "status": "unavailable", "history": None,
            "reason": "invalid_instrument_selection",
        }


def test_freshness_cannot_hide_missing_latest_expected_session():
    missing = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06", "2026-11-07"],
        now=NOW, rights_reviewed=True, max_latest_age_seconds=86400 * 3,
        expected_instrument_id="MSFT",
    )
    assert missing == {
        "status": "unavailable", "history": None,
        "reason": "latest_expected_session_missing",
    }
    complete = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"],
        now=NOW, rights_reviewed=True, max_latest_age_seconds=86400 * 3,
        expected_instrument_id="MSFT",
    )
    assert complete["status"] == "verified_metadata"
    assert complete["latestExpectedSessionMissing"] is False


def test_latest_bar_projection_keeps_observed_price_volume_and_pit():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert result["status"] == "verified_metadata"
    assert result["latestBar"] == result["history"]["bars"][-1]
    assert result["latestBar"]["close"] == 10.5
    assert result["latestBar"]["volume"] == 1000
    assert result["latestBar"]["availableAt"] == result["latestAvailableAt"]
    assert result["history"]["operationallyVerified"] is False


def test_latest_bar_is_never_exposed_without_rights_or_for_wrong_instrument():
    for rights, instrument in ((False, "MSFT"), (True, "AAPL")):
        result = build_pilot_history_view(
            [BAR], expected_sessions=["2026-11-06"], now=NOW,
            rights_reviewed=rights, expected_instrument_id=instrument,
        )
        assert result["status"] == "unavailable"
        assert "latestBar" not in result
        assert result["history"] is None


def test_missing_latest_session_never_projects_old_close_as_current_quote():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06", "2026-11-07"],
        now=NOW, rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert result["status"] == "verified_metadata"
    assert result["latestExpectedSessionMissing"] is True
    assert result["latestBar"] is None
    assert result["lastObservedBar"]["session"] == "2026-11-06"
    assert result["lastObservedBar"]["close"] == 10.5
    assert result["latestObservationAt"] == result["lastObservedBar"]["observationAt"]
    assert result["history"]["operationallyVerified"] is False


def test_complete_latest_session_preserves_quote_and_last_observed_bar():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert result["latestExpectedSessionMissing"] is False
    assert result["latestBar"] == result["lastObservedBar"]
    assert result["latestBar"]["close"] == 10.5


def test_current_quote_eligibility_requires_explicit_freshness_policy():
    no_policy = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert no_policy["latestBar"] is not None  # Historical bar remains visible.
    assert no_policy["currentQuoteEligible"] is False
    assert no_policy["currentQuoteEligibilityReason"] == "freshness_policy_not_supplied"

    policy = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
        max_latest_age_seconds=86400 * 3,
    )
    assert policy["currentQuoteEligible"] is True
    assert policy["currentQuoteEligibilityReason"] == "freshness_policy_satisfied_metadata_only"
    assert policy["history"]["operationallyVerified"] is False


def test_missing_latest_session_cannot_be_eligible_for_current_quote():
    result = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06", "2026-11-07"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
    )
    assert result["currentQuoteEligible"] is False
    assert result["currentQuoteEligibilityReason"] == "latest_expected_session_missing"
    assert result["latestBar"] is None


def test_history_source_and_license_must_match_independent_selection():
    accepted = build_pilot_history_view(
        [BAR], expected_sessions=["2026-11-06"], now=NOW,
        rights_reviewed=True, expected_instrument_id="MSFT",
        expected_source="test-only", expected_license_ref="test-only-not-a-license",
    )
    assert accepted["status"] == "verified_metadata"
    assert accepted["history"]["operationallyVerified"] is False

    for field, value, reason in (
        ("expected_source", "other-provider", "source_mismatch"),
        ("expected_license_ref", "other-license", "license_mismatch"),
        ("expected_source", " test-only", "invalid_source_selection"),
        ("expected_license_ref", "test-only-not-a-license\n", "invalid_source_selection"),
        ("expected_source", True, "invalid_source_selection"),
    ):
        result = build_pilot_history_view(
            [BAR], expected_sessions=["2026-11-06"], now=NOW,
            rights_reviewed=True, **{field: value},
        )
        assert result == {"status": "unavailable", "history": None, "reason": reason}
        assert "latestBar" not in result

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

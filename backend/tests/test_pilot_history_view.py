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

from datetime import datetime, timezone

import pytest

from app.services.corporate_action_reconciliation_service import (
    CorporateActionReconciliationEvent,
    CorporateActionReconciliationReport,
)
from app.services.historical_market_acceptance_service import (
    HistoricalMarketAcceptanceService,
)
from app.services.market_observation_coverage_service import (
    MarketObservationCoverageReport,
)


def _coverage(*, eligible=2, deep=2, current_deep=None, minimum_days=365):
    effective_current = deep if current_deep is None else current_deep
    return MarketObservationCoverageReport(
        active_instrument_count=eligible,
        history_eligible_instrument_count=eligible,
        covered_instrument_count=eligible,
        deep_history_instrument_count=deep,
        current_deep_history_instrument_count=effective_current,
        observation_count=1000,
        earliest_observed_at="2025-01-01T00:00:00+00:00",
        latest_observed_at="2026-09-11T00:00:00+00:00",
        by_source={"yahoo": {"observationCount": 1000}},
        minimum_history_days=minimum_days,
        minimum_deep_history_coverage=0.30,
        as_of="2026-09-11T00:00:00+00:00",
    )


def _reconciliation(status="agreed"):
    event = CorporateActionReconciliationEvent(
        action_type="split",
        effective_at="2026-01-02T00:00:00+00:00",
        status=status,
        providers_present=("primary", "secondary"),
        providers_missing=() if status != "incomplete" else ("secondary",),
        values_by_provider={
            "primary": {"splitRatio": 2.0},
            "secondary": {"splitRatio": 2.0 if status != "conflict" else 3.0},
        },
    )
    return CorporateActionReconciliationReport(
        instrument_id=1,
        source_providers=("primary", "secondary"),
        knowledge_cutoff=datetime(2026, 9, 11, tzinfo=timezone.utc),
        events=(event,),
    )


def test_acceptance_requires_full_365_day_universe_current_to_pit_cutoff_and_secondary_agreement():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is True
    assert report.corporate_action_gate_passed is True
    assert report.history_acceptance_passed is True
    api = report.to_api_dict()
    assert api["requiredHistoryDays"] == 365
    assert api["requiredDeepHistoryCoverage"] == 1.0
    assert api["measuredCurrentDeepHistoryCoverage"] == 1.0
    assert api["pointInTimeCutoffApplied"] is True
    assert api["automaticCanonicalization"] is False
    assert api["automaticPriceAdjustment"] is False
    assert api["productionAuthorization"] is False


def test_partial_universe_depth_fails_even_when_legacy_diagnostic_would_pass():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(eligible=10, deep=3, current_deep=3),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.coverage.deep_history_coverage == 0.3
    assert report.depth_gate_passed is False
    assert report.history_acceptance_passed is False


def test_stale_deep_history_fails_when_it_does_not_reach_pit_cutoff():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(eligible=2, deep=2, current_deep=1),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.coverage.deep_history_coverage == 1.0
    assert report.coverage.current_deep_history_coverage == 0.5
    assert report.depth_gate_passed is False
    assert report.history_acceptance_passed is False


def test_missing_pit_cutoff_fails_closed():
    coverage = _coverage()
    coverage = MarketObservationCoverageReport(
        **{**coverage.__dict__, "as_of": None}
    )
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=coverage,
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is False


def test_secondary_source_must_be_explicitly_verified_not_inferred_from_fixture_names():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=False,
    )
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


@pytest.mark.parametrize("status", ["conflict", "incomplete"])
def test_conflict_or_missing_provider_fails_closed(status):
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation(status)],
        independent_secondary_source_verified=True,
    )
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


def test_no_measured_agreed_event_does_not_claim_secondary_agreement():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[],
        independent_secondary_source_verified=True,
    )
    assert report.agreed_event_count == 0
    assert report.corporate_action_gate_passed is False


def test_cannot_lower_final_history_threshold_below_365_days():
    with pytest.raises(ValueError, match="365"):
        HistoricalMarketAcceptanceService(required_history_days=364)


@pytest.mark.parametrize(
    "unverified",
    ["false", "true", "yes", 1, 0, None, [], {}],
)
def test_secondary_source_acceptance_rejects_truthy_non_boolean_flags(
    unverified,
):
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=unverified,
    )
    assert report.independent_secondary_source_verified is False
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["independentSecondarySourceVerified"] is False


def test_direct_report_construction_cannot_bypass_explicit_secondary_verification():
    from dataclasses import replace

    verified = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert verified.corporate_action_gate_passed is True
    unverified = replace(verified, independent_secondary_source_verified="false")
    assert unverified.corporate_action_gate_passed is False
    assert unverified.history_acceptance_passed is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"active_instrument_count": 1},
        {"covered_instrument_count": 1},
        {"deep_history_instrument_count": 1},
        {"current_deep_history_instrument_count": 1},
    ],
)
def test_inconsistent_universe_counts_cannot_pass_history_acceptance(overrides):
    from dataclasses import replace

    coverage = replace(_coverage(), **overrides)
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=coverage,
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["productionAuthorization"] is False


@pytest.mark.parametrize(
    "providers",
    [("primary", "primary"), ("primary", " PRIMARY "), ("primary", "")],
)
def test_acceptance_rejects_duplicate_or_blank_provider_evidence(providers):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), source_providers=providers)],
        independent_secondary_source_verified=True,
    )
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


@pytest.mark.parametrize(
    "knowledge_cutoff",
    [datetime(2026, 9, 12, tzinfo=timezone.utc), datetime(2026, 9, 11)],
)
def test_reconciliation_cannot_use_future_or_naive_pit_evidence(knowledge_cutoff):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), knowledge_cutoff=knowledge_cutoff)],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is True
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


def test_reconciliation_same_instant_with_offset_remains_pit_valid():
    from dataclasses import replace
    from datetime import timedelta

    offset_cutoff = datetime(2026, 9, 11, 2, tzinfo=timezone(timedelta(hours=2)))
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), knowledge_cutoff=offset_cutoff)],
        independent_secondary_source_verified=True,
    )
    assert report.corporate_action_gate_passed is True
    assert report.history_acceptance_passed is True


@pytest.mark.parametrize(
    "knowledge_cutoff",
    [
        datetime(2026, 9, 10, tzinfo=timezone.utc),
        datetime(2026, 9, 11, 1, tzinfo=timezone.utc),
    ],
)
def test_reconciliation_must_cover_exact_market_pit_instant(knowledge_cutoff):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), knowledge_cutoff=knowledge_cutoff)],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is True
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["productionAuthorization"] is False


@pytest.mark.parametrize("invalid_instrument_id", [0, -1])
def test_reconciliation_rejects_invalid_instrument_identity(invalid_instrument_id):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), instrument_id=invalid_instrument_id)],
        independent_secondary_source_verified=True,
    )
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


def test_reconciliation_rejects_duplicate_instrument_evidence():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[_reconciliation(), _reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.agreed_event_count == 2
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


@pytest.mark.parametrize("maximum_gap_days", [0, 8, 30, 365])
def test_historical_acceptance_rejects_relaxed_source_continuity(maximum_gap_days):
    from dataclasses import replace

    coverage = replace(_coverage(), maximum_source_gap_days=maximum_gap_days)
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=coverage,
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["productionAuthorization"] is False


@pytest.mark.parametrize("as_of", ["", "not-a-date", "2026-09-11T00:00:00", None])
def test_historical_depth_rejects_invalid_or_naive_pit_cutoff(as_of):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=replace(_coverage(), as_of=as_of),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is False
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["pointInTimeCutoffApplied"] is False


@pytest.mark.parametrize(
    "providers",
    [("yahoo", "yahoo_finance"), ("YAHOO_FINANCE", " yahoo "), ("primary", 123)],
)
def test_historical_acceptance_rejects_same_family_or_nontext_providers(providers):
    from dataclasses import replace

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[replace(_reconciliation(), source_providers=providers)],
        independent_secondary_source_verified=True,
    )
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False


@pytest.mark.parametrize(
    "event_changes",
    [
        {"providers_present": ("primary",)},
        {"providers_missing": ("secondary",)},
        {"values_by_provider": {"primary": {"splitRatio": 2.0}}},
        {"values_by_provider": {"primary": {}, "secondary": {"splitRatio": 2.0}}},
        {"effective_at": "2026-09-12T00:00:00+00:00"},
        {"effective_at": "2026-01-02T00:00:00"},
        {"action_type": "merger"},
    ],
)
def test_historical_acceptance_rejects_contradictory_agreed_event_evidence(event_changes):
    from dataclasses import replace

    original = _reconciliation()
    forged = replace(
        original,
        events=(replace(original.events[0], **event_changes),),
    )
    assert forged.agreed_event_count == 1
    assert forged.reconciled is True

    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(),
        reconciliation_reports=[forged],
        independent_secondary_source_verified=True,
    )
    assert report.depth_gate_passed is True
    assert report.corporate_action_gate_passed is False
    assert report.history_acceptance_passed is False
    assert report.to_api_dict()["productionAuthorization"] is False

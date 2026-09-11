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


def _coverage(*, eligible=2, deep=2, minimum_days=365):
    return MarketObservationCoverageReport(
        active_instrument_count=eligible,
        history_eligible_instrument_count=eligible,
        covered_instrument_count=eligible,
        deep_history_instrument_count=deep,
        observation_count=1000,
        earliest_observed_at="2025-01-01T00:00:00+00:00",
        latest_observed_at="2026-09-11T00:00:00+00:00",
        by_source={"yahoo": {"observationCount": 1000}},
        minimum_history_days=minimum_days,
        minimum_deep_history_coverage=0.30,
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


def test_acceptance_requires_full_365_day_universe_and_secondary_agreement():
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
    assert api["automaticCanonicalization"] is False
    assert api["automaticPriceAdjustment"] is False
    assert api["productionAuthorization"] is False


def test_partial_universe_depth_fails_even_when_legacy_diagnostic_would_pass():
    report = HistoricalMarketAcceptanceService().evaluate(
        coverage=_coverage(eligible=10, deep=3),
        reconciliation_reports=[_reconciliation()],
        independent_secondary_source_verified=True,
    )
    assert report.coverage.deep_history_coverage == 0.3
    assert report.depth_gate_passed is False
    assert report.history_acceptance_passed is False


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

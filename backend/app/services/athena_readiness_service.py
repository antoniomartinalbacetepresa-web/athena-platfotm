from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.services.corporate_action_coverage_service import CorporateActionCoverageService
from app.services.instrument_type_market_cap_service import (
    InstrumentTypeMarketCapService,
)
from app.services.market_observation_coverage_service import (
    MarketObservationCoverageService,
)
from app.services.market_weighting_readiness_service import (
    MarketWeightingReadinessService,
)
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


_FINAL_REQUIRED_HISTORY_DAYS = 365
_FINAL_REQUIRED_DEEP_HISTORY_COVERAGE = 1.0


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_integral_count(value: Any) -> int | None:
    """Reject fabricated/contradictory counts in readiness payloads."""
    number = _finite_number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _final_market_history_depth_passed(market_history: dict[str, Any]) -> bool:
    """Require a coherent, PIT-current, 365-day eligible-universe history."""

    active = _nonnegative_integral_count(market_history.get("activeInstrumentCount"))
    eligible = _nonnegative_integral_count(
        market_history.get("historyEligibleInstrumentCount")
    )
    covered = _nonnegative_integral_count(
        market_history.get("coveredInstrumentCount")
    )
    deep = _nonnegative_integral_count(
        market_history.get("deepHistoryInstrumentCount")
    )
    current_deep = _nonnegative_integral_count(
        market_history.get("currentDeepHistoryInstrumentCount")
    )
    deep_coverage = _finite_number(market_history.get("deepHistoryCoverage"))
    current_coverage = _finite_number(
        market_history.get("currentDeepHistoryCoverage")
    )
    minimum_days = _nonnegative_integral_count(
        market_history.get("minimumHistoryDays")
    )
    maximum_gap_days = _nonnegative_integral_count(
        market_history.get("maximumSourceGapDays")
    )

    cutoff_text = market_history.get("asOf")
    if not isinstance(cutoff_text, str) or not cutoff_text.strip():
        return False
    try:
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return False

    return (
        market_history.get("historyDepthReady") is True
        and market_history.get("currentHistoryDepthReady") is True
        and market_history.get("sourceContinuityRequired") is True
        and market_history.get("pointInTimeCutoffApplied") is True
        and active is not None
        and eligible is not None
        and eligible > 0
        and active >= eligible
        and covered == eligible
        and deep == eligible
        and current_deep == eligible
        and deep_coverage == _FINAL_REQUIRED_DEEP_HISTORY_COVERAGE
        and current_coverage == _FINAL_REQUIRED_DEEP_HISTORY_COVERAGE
        and minimum_days is not None
        and minimum_days >= _FINAL_REQUIRED_HISTORY_DAYS
        and maximum_gap_days is not None
        and 0 < maximum_gap_days <= 7
    )

def _final_corporate_actions_passed(corporate_actions: dict[str, Any]) -> bool:
    """Require measured cross-family agreement, not a manual verification flag."""

    event_count = _nonnegative_integral_count(corporate_actions.get("eventCount"))
    agreed = _nonnegative_integral_count(corporate_actions.get("agreedEventCount"))
    conflicts = _nonnegative_integral_count(corporate_actions.get("conflictEventCount"))
    incomplete = _nonnegative_integral_count(corporate_actions.get("incompleteEventCount"))
    coverage = _finite_number(corporate_actions.get("agreementCoverage"))
    families = corporate_actions.get("independentProviderFamilies")

    return (
        corporate_actions.get("crossProviderReconciliationReady") is True
        and corporate_actions.get("automaticCanonicalization") is False
        and corporate_actions.get("productionIndependenceClaimed") is False
        and isinstance(families, list)
        and all(isinstance(item, str) and bool(item.strip()) for item in families)
        and len({item.strip().casefold() for item in families}) >= 2
        and event_count is not None
        and event_count > 0
        and agreed is not None
        and agreed == event_count
        and conflicts == 0
        and incomplete == 0
        and coverage is not None
        and math.isclose(coverage, 1.0, rel_tol=0.0, abs_tol=1e-12)
    )


def _final_forecast_error_oos_passed(forecast_error: dict[str, Any]) -> bool:
    """Require internally reconciled, complete OOS measurement evidence."""

    if forecast_error.get("status") != "forecast_error_oos_evidence_available":
        return False

    eligible = _nonnegative_integral_count(forecast_error.get("eligibleOutcomeCount"))
    measured = _nonnegative_integral_count(forecast_error.get("forecastErrorCount"))
    missing = _nonnegative_integral_count(forecast_error.get("missingForecastErrorCount"))
    coverage = _finite_number(forecast_error.get("measurementCoverage"))
    horizon_count = _nonnegative_integral_count(forecast_error.get("horizonCount"))
    horizons = forecast_error.get("horizons")

    if (
        eligible is None
        or eligible <= 0
        or measured is None
        or measured != eligible
        or missing != 0
        or coverage is None
        or not math.isclose(coverage, 1.0, rel_tol=0.0, abs_tol=1e-12)
        or horizon_count is None
        or horizon_count <= 0
        or not isinstance(horizons, dict)
        or len(horizons) != horizon_count
    ):
        return False

    horizon_eligible_total = 0.0
    horizon_measured_total = 0.0
    for horizon in horizons.values():
        if not isinstance(horizon, dict):
            return False
        horizon_eligible = _nonnegative_integral_count(horizon.get("eligibleOutcomeCount"))
        horizon_measured = _nonnegative_integral_count(horizon.get("forecastErrorCount"))
        horizon_missing = _nonnegative_integral_count(horizon.get("missingForecastErrorCount"))
        horizon_coverage = _finite_number(horizon.get("measurementCoverage"))
        if (
            horizon_eligible is None
            or horizon_eligible <= 0
            or horizon_measured is None
            or horizon_measured != horizon_eligible
            or horizon_missing != 0
            or horizon_coverage is None
            or not math.isclose(horizon_coverage, 1.0, rel_tol=0.0, abs_tol=1e-12)
        ):
            return False
        horizon_eligible_total += horizon_eligible
        horizon_measured_total += horizon_measured

    return horizon_eligible_total == eligible and horizon_measured_total == measured


def _final_forecast_error_longitudinal_sufficiency_passed(
    forecast_error: dict[str, Any],
) -> bool:
    distinct_periods = _finite_number(
        forecast_error.get("distinctEvaluationPeriodCount")
    )
    span_days = _finite_number(forecast_error.get("evaluationSpanDays"))
    sufficiency = forecast_error.get("longitudinalSufficiency")
    if not isinstance(sufficiency, dict):
        return False
    policy_id = sufficiency.get("policyId")

    return (
        forecast_error.get("longitudinalEvidenceStatus")
        == "multiple_evaluation_periods_observed"
        and distinct_periods is not None
        and distinct_periods >= 2
        and span_days is not None
        and span_days > 0
        and sufficiency.get("status") == "precommitted_policy_satisfied"
        and isinstance(policy_id, str)
        and bool(policy_id.strip())
        and sufficiency.get("policyApproved") is True
        and sufficiency.get("acceptanceEvidenceVerified") is True
    )


def build_operational_readiness(
    *,
    universe: dict[str, Any],
    weighting: dict[str, Any],
    market_history: dict[str, Any],
    corporate_actions: dict[str, Any],
    learning: dict[str, Any],
) -> dict[str, Any]:
    research_outcome = learning.get("researchOutcomeOos")
    forecast_error = learning.get("researchForecastErrorOos")
    if not isinstance(research_outcome, dict):
        research_outcome = {}
    if not isinstance(forecast_error, dict):
        forecast_error = {}

    gates = [
        {"id": "global_market_universe", "passed": universe.get("isGlobalReady") is True, "blocker": "global_market_universe_not_ready"},
        {"id": "canonical_market_weighting", "passed": weighting.get("ready") is True, "blocker": "canonical_market_weighting_not_ready"},
        {"id": "market_history_depth", "passed": _final_market_history_depth_passed(market_history), "blocker": "market_history_depth_insufficient"},
        {"id": "corporate_actions_cross_provider_reconciliation", "passed": _final_corporate_actions_passed(corporate_actions), "blocker": "corporate_actions_independent_reconciliation_pending"},
        {"id": "research_outcome_oos_evidence", "passed": research_outcome.get("status") == "research_outcome_oos_evidence_available", "blocker": "research_outcome_oos_evidence_pending"},
        {"id": "forecast_error_oos_complete", "passed": _final_forecast_error_oos_passed(forecast_error), "blocker": "forecast_error_oos_measurement_incomplete"},
        {"id": "forecast_error_oos_longitudinal_sufficiency", "passed": _final_forecast_error_longitudinal_sufficiency_passed(forecast_error), "blocker": "forecast_error_oos_longitudinal_sufficiency_pending"},
    ]

    weighting_blockers = weighting.get("blockers")
    inherited_weighting_blockers = [str(item) for item in weighting_blockers] if isinstance(weighting_blockers, list) else []
    blockers = [str(gate["blocker"]) for gate in gates if gate["passed"] is not True]
    for blocker in inherited_weighting_blockers:
        if blocker not in blockers:
            blockers.append(blocker)

    passed_gate_count = sum(1 for gate in gates if gate["passed"] is True)
    total_gate_count = len(gates)
    completion_percent = round((passed_gate_count / total_gate_count) * 100.0, 1) if total_gate_count else 0.0

    return {
        "scope": "operational_evidence_readiness_not_product_feature_completeness",
        "completionPercent": completion_percent,
        "passedGateCount": passed_gate_count,
        "totalGateCount": total_gate_count,
        "ready": passed_gate_count == total_gate_count,
        "gates": gates,
        "blockers": blockers,
        "policy": {
            "oneHundredPercentMeaning": "all_current_operational_evidence_gates_passed_only",
            "featureCompletenessClaimed": False,
            "productionEligibilityClaimed": False,
            "automaticTrading": False,
        },
    }


def build_readiness_report(
    *,
    database: AthenaDatabase | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    effective_database = database if database is not None else AthenaDatabase()
    effective_as_of = as_of if as_of is not None else datetime.now(timezone.utc)
    if effective_as_of.tzinfo is None or effective_as_of.utcoffset() is None:
        raise ValueError("as_of debe incluir zona horaria.")

    universe = PersistedMarketUniverseService(database=effective_database).get_quality_report().to_api_dict()
    weighting = MarketWeightingReadinessService(database=effective_database).get_report(as_of=effective_as_of).to_api_dict()
    instrument_types = InstrumentTypeMarketCapService(database=effective_database).get_report().to_api_dict()
    market_history = MarketObservationCoverageService(database=effective_database).get_report(as_of=effective_as_of).to_api_dict()
    corporate_actions = CorporateActionCoverageService(database=effective_database).get_report(as_of=effective_as_of).to_api_dict()
    learning = RecommendationLearningStatusService(database=effective_database).get_status(as_of=effective_as_of)
    operational_readiness = build_operational_readiness(
        universe=universe,
        weighting=weighting,
        market_history=market_history,
        corporate_actions=corporate_actions,
        learning=learning,
    )

    return {
        "status": "athena_readiness_diagnostics",
        "asOf": effective_as_of.astimezone(timezone.utc).isoformat(),
        "operationalReadiness": operational_readiness,
        "marketUniverse": universe,
        "marketWeighting": weighting,
        "instrumentTypes": instrument_types,
        "marketHistory": market_history,
        "marketHistoryGapDiagnostics": {
            "endpoint": "/api/v1/readiness/market-history/gaps",
            "method": "GET",
            "asOfParameter": "asOf",
            "readOnly": True,
            "productionEvidenceClaimed": False,
        },
        "corporateActions": corporate_actions,
        "recommendationLearning": learning,
        "automaticActivation": False,
    }

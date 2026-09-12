from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.database.athena_database import AthenaDatabase
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


def _final_market_history_depth_passed(market_history: dict[str, Any]) -> bool:
    """Require final-depth evidence, not the lower operational diagnostic threshold.

    ``historyDepthReady`` intentionally uses the coverage service's configurable
    diagnostic threshold (currently 30%). That signal is useful for incremental
    operations, but it must never be promoted into the final readiness gate. The
    final gate requires one-provider continuity for at least 365 days across the
    entire eligible universe and fails closed when any evidence field is absent.
    """

    eligible = _finite_number(market_history.get("historyEligibleInstrumentCount"))
    deep = _finite_number(market_history.get("deepHistoryInstrumentCount"))
    coverage = _finite_number(market_history.get("deepHistoryCoverage"))
    minimum_days = _finite_number(market_history.get("minimumHistoryDays"))

    return (
        market_history.get("historyDepthReady") is True
        and market_history.get("sourceContinuityRequired") is True
        and eligible is not None
        and eligible > 0
        and deep is not None
        and deep >= eligible
        and coverage is not None
        and coverage >= _FINAL_REQUIRED_DEEP_HISTORY_COVERAGE
        and minimum_days is not None
        and minimum_days >= _FINAL_REQUIRED_HISTORY_DAYS
    )


def build_operational_readiness(
    *,
    universe: dict[str, Any],
    weighting: dict[str, Any],
    market_history: dict[str, Any],
    learning: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate only explicit, evidence-backed operational gates.

    A 100% value here means every currently modelled operational evidence gate
    is satisfied. It does not mean the whole product is feature-complete, safe
    for production promotion, or authorized for automatic trading.
    """

    research_outcome = learning.get("researchOutcomeOos")
    forecast_error = learning.get("researchForecastErrorOos")
    if not isinstance(research_outcome, dict):
        research_outcome = {}
    if not isinstance(forecast_error, dict):
        forecast_error = {}

    forecast_measurement_coverage = forecast_error.get("measurementCoverage")
    forecast_measurement_complete = (
        isinstance(forecast_measurement_coverage, (int, float))
        and not isinstance(forecast_measurement_coverage, bool)
        and math.isfinite(float(forecast_measurement_coverage))
        and float(forecast_measurement_coverage) >= 1.0
    )

    gates = [
        {
            "id": "global_market_universe",
            "passed": universe.get("isGlobalReady") is True,
            "blocker": "global_market_universe_not_ready",
        },
        {
            "id": "canonical_market_weighting",
            "passed": weighting.get("ready") is True,
            "blocker": "canonical_market_weighting_not_ready",
        },
        {
            "id": "market_history_depth",
            "passed": _final_market_history_depth_passed(market_history),
            "blocker": "market_history_depth_insufficient",
        },
        {
            "id": "research_outcome_oos_evidence",
            "passed": (
                research_outcome.get("status")
                == "research_outcome_oos_evidence_available"
            ),
            "blocker": "research_outcome_oos_evidence_pending",
        },
        {
            "id": "forecast_error_oos_complete",
            "passed": (
                forecast_error.get("status")
                == "forecast_error_oos_evidence_available"
                and forecast_measurement_complete
            ),
            "blocker": "forecast_error_oos_measurement_incomplete",
        },
    ]

    weighting_blockers = weighting.get("blockers")
    inherited_weighting_blockers = (
        [str(item) for item in weighting_blockers]
        if isinstance(weighting_blockers, list)
        else []
    )
    blockers = [
        str(gate["blocker"])
        for gate in gates
        if gate["passed"] is not True
    ]
    for blocker in inherited_weighting_blockers:
        if blocker not in blockers:
            blockers.append(blocker)

    passed_gate_count = sum(1 for gate in gates if gate["passed"] is True)
    total_gate_count = len(gates)
    completion_percent = (
        round((passed_gate_count / total_gate_count) * 100.0, 1)
        if total_gate_count
        else 0.0
    )

    return {
        "scope": "operational_evidence_readiness_not_product_feature_completeness",
        "completionPercent": completion_percent,
        "passedGateCount": passed_gate_count,
        "totalGateCount": total_gate_count,
        "ready": passed_gate_count == total_gate_count,
        "gates": gates,
        "blockers": blockers,
        "policy": {
            "oneHundredPercentMeaning": (
                "all_current_operational_evidence_gates_passed_only"
            ),
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

    universe = PersistedMarketUniverseService(
        database=effective_database,
    ).get_quality_report().to_api_dict()
    weighting = MarketWeightingReadinessService(
        database=effective_database,
    ).get_report(as_of=effective_as_of).to_api_dict()
    instrument_types = InstrumentTypeMarketCapService(
        database=effective_database,
    ).get_report().to_api_dict()
    market_history = MarketObservationCoverageService(
        database=effective_database,
    ).get_report().to_api_dict()
    learning = RecommendationLearningStatusService(
        database=effective_database,
    ).get_status(
        as_of=effective_as_of,
    )
    operational_readiness = build_operational_readiness(
        universe=universe,
        weighting=weighting,
        market_history=market_history,
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
        "recommendationLearning": learning,
        "automaticActivation": False,
    }

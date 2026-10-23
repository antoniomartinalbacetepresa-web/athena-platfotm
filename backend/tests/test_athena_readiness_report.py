from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.athena_readiness_service import build_operational_readiness
from scripts.athena_readiness_report import build_report


def _complete_market_history() -> dict[str, object]:
    return {
        "historyDepthReady": True,
        "currentHistoryDepthReady": True,
        "sourceContinuityRequired": True,
        "pointInTimeCutoffApplied": True,
        "asOf": "2026-09-01T21:00:00+00:00",
        "activeInstrumentCount": 10,
        "historyEligibleInstrumentCount": 10,
        "coveredInstrumentCount": 10,
        "maximumSourceGapDays": 7,
        "deepHistoryInstrumentCount": 10,
        "deepHistoryCoverage": 1.0,
        "currentDeepHistoryInstrumentCount": 10,
        "currentDeepHistoryCoverage": 1.0,
        "minimumHistoryDays": 365,
    }


def _complete_corporate_actions() -> dict[str, object]:
    return {
        "crossProviderReconciliationReady": True,
        "automaticCanonicalization": False,
        "productionIndependenceClaimed": False,
        "eventCount": 2,
        "agreedEventCount": 2,
        "conflictEventCount": 0,
        "incompleteEventCount": 0,
        "agreementCoverage": 1.0,
        "independentProviderFamilies": ["yahoo", "exchange"],
    }


def _complete_learning(*, forecast_coverage: float = 1.0) -> dict[str, object]:
    return {
        "researchOutcomeOos": {"status": "research_outcome_oos_evidence_available"},
        "researchForecastErrorOos": {
            "status": "forecast_error_oos_evidence_available",
            "eligibleOutcomeCount": 2,
            "forecastErrorCount": 2,
            "missingForecastErrorCount": 0,
            "measurementCoverage": forecast_coverage,
            "distinctEvaluationPeriodCount": 2,
            "evaluationSpanDays": 30.0,
            "longitudinalEvidenceStatus": "multiple_evaluation_periods_observed",
            "longitudinalSufficiency": {
                "status": "precommitted_policy_satisfied",
                "policyId": "test-policy-only",
                "policyApproved": True,
                "acceptanceEvidenceVerified": True,
            },
            "horizonCount": 1,
            "horizons": {
                "604800": {
                    "eligibleOutcomeCount": 2,
                    "forecastErrorCount": 2,
                    "missingForecastErrorCount": 0,
                    "measurementCoverage": 1.0,
                }
            },
        },
    }


def _readiness(*, market_history=None, corporate_actions=None, learning=None):
    return build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history=market_history or _complete_market_history(),
        corporate_actions=corporate_actions or _complete_corporate_actions(),
        learning=learning or _complete_learning(),
    )


def test_athena_readiness_report_is_read_only_and_conservative(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    report = build_report(
        database=database,
        as_of=datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
    )
    assert report["status"] == "athena_readiness_diagnostics"
    assert report["automaticActivation"] is False
    assert report["marketUniverse"]["isGlobalReady"] is False
    assert report["marketWeighting"]["ready"] is False
    assert "external_market_cap_validation_required" in report["marketWeighting"]["blockers"]
    assert report["instrumentTypes"]["listingCount"] == 0
    assert report["marketHistory"]["observationCount"] == 0
    assert report["marketHistory"]["instrumentCoverage"] == 0.0
    assert report["marketHistory"]["historyDepthReady"] is False
    assert report["marketHistory"]["currentHistoryDepthReady"] is False
    assert report["marketHistory"]["pointInTimeCutoffApplied"] is True
    assert report["corporateActions"]["eventCount"] == 0
    assert report["corporateActions"]["crossProviderReconciliationReady"] is False
    assert report["corporateActions"]["productionIndependenceClaimed"] is False
    assert report["recommendationLearning"]["automaticModelMutation"] is False

    readiness = report["operationalReadiness"]
    assert readiness["scope"] == "operational_evidence_readiness_not_product_feature_completeness"
    assert readiness["completionPercent"] == 0.0
    assert readiness["passedGateCount"] == 0
    assert readiness["totalGateCount"] == 7
    assert readiness["ready"] is False
    assert "global_market_universe_not_ready" in readiness["blockers"]
    assert "canonical_market_weighting_not_ready" in readiness["blockers"]
    assert "market_history_depth_insufficient" in readiness["blockers"]
    assert "corporate_actions_independent_reconciliation_pending" in readiness["blockers"]
    assert "research_outcome_oos_evidence_pending" in readiness["blockers"]
    assert "forecast_error_oos_measurement_incomplete" in readiness["blockers"]
    assert "forecast_error_oos_longitudinal_sufficiency_pending" in readiness["blockers"]
    assert "external_market_cap_validation_required" in readiness["blockers"]
    assert readiness["policy"]["featureCompletenessClaimed"] is False
    assert readiness["policy"]["productionEligibilityClaimed"] is False
    assert readiness["policy"]["automaticTrading"] is False


def test_operational_readiness_reaches_100_only_when_all_gates_pass() -> None:
    report = _readiness()
    assert report["completionPercent"] == 100.0
    assert report["passedGateCount"] == 7
    assert report["totalGateCount"] == 7
    assert report["ready"] is True
    assert report["blockers"] == []
    assert all(gate["passed"] is True for gate in report["gates"])
    assert report["policy"]["oneHundredPercentMeaning"] == "all_current_operational_evidence_gates_passed_only"
    assert report["policy"]["featureCompletenessClaimed"] is False


def test_operational_readiness_requires_full_forecast_error_coverage() -> None:
    report = _readiness(learning=_complete_learning(forecast_coverage=0.99))
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]


def test_operational_readiness_rejects_forecast_coverage_above_one() -> None:
    report = _readiness(learning=_complete_learning(forecast_coverage=1.01))
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]


def test_operational_readiness_reconciles_forecast_counts_and_horizons() -> None:
    learning = _complete_learning()
    forecast = learning["researchForecastErrorOos"]
    assert isinstance(forecast, dict)
    forecast["forecastErrorCount"] = 1
    report = _readiness(learning=learning)
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]

    learning = _complete_learning()
    forecast = learning["researchForecastErrorOos"]
    assert isinstance(forecast, dict)
    horizons = forecast["horizons"]
    assert isinstance(horizons, dict)
    horizon = horizons["604800"]
    assert isinstance(horizon, dict)
    horizon["missingForecastErrorCount"] = 1
    report = _readiness(learning=learning)
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]


def test_operational_readiness_rejects_snapshot_or_unapproved_longitudinal_evidence() -> None:
    learning = _complete_learning()
    forecast = learning["researchForecastErrorOos"]
    assert isinstance(forecast, dict)
    forecast["distinctEvaluationPeriodCount"] = 1
    forecast["evaluationSpanDays"] = 0.0
    forecast["longitudinalEvidenceStatus"] = "single_period_snapshot"
    report = _readiness(learning=learning)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_longitudinal_sufficiency_pending"]

    learning = _complete_learning()
    forecast = learning["researchForecastErrorOos"]
    assert isinstance(forecast, dict)
    forecast["longitudinalSufficiency"] = {
        "status": "policy_not_precommitted",
        "policyId": None,
        "policyApproved": False,
        "acceptanceEvidenceVerified": False,
    }
    report = _readiness(learning=learning)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_longitudinal_sufficiency_pending"]


def test_operational_readiness_rejects_shallow_history() -> None:
    history = _complete_market_history()
    history["historyDepthReady"] = False
    report = _readiness(market_history=history)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_stale_deep_history() -> None:
    history = _complete_market_history()
    history["currentDeepHistoryInstrumentCount"] = 9
    history["currentDeepHistoryCoverage"] = 0.9
    history["currentHistoryDepthReady"] = True
    report = _readiness(market_history=history)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_history_without_pit_cutoff_evidence() -> None:
    history = _complete_market_history()
    history["pointInTimeCutoffApplied"] = False
    report = _readiness(market_history=history)
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_legacy_30_percent_history_threshold() -> None:
    history = _complete_market_history()
    history.update({
        "historyEligibleInstrumentCount": 10,
        "deepHistoryInstrumentCount": 3,
        "deepHistoryCoverage": 0.3,
        "currentDeepHistoryInstrumentCount": 3,
        "currentDeepHistoryCoverage": 0.3,
    })
    report = _readiness(market_history=history)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_fails_closed_when_final_history_evidence_is_missing() -> None:
    report = _readiness(market_history={"historyDepthReady": True})
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_non_finite_forecast_coverage() -> None:
    report = _readiness(learning=_complete_learning(forecast_coverage=float("inf")))
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]


def test_operational_readiness_rejects_unmeasured_or_single_family_corporate_actions() -> None:
    weak_evidence = _complete_corporate_actions()
    weak_evidence["independentProviderFamilies"] = ["yahoo"]
    report = _readiness(corporate_actions=weak_evidence)
    assert report["completionPercent"] == 85.7
    assert report["ready"] is False
    assert report["blockers"] == ["corporate_actions_independent_reconciliation_pending"]

    non_finite_evidence = _complete_corporate_actions()
    non_finite_evidence["agreementCoverage"] = float("inf")
    report = _readiness(corporate_actions=non_finite_evidence)
    assert report["ready"] is False
    assert "corporate_actions_independent_reconciliation_pending" in report["blockers"]


def test_athena_readiness_report_requires_timezone_aware_as_of(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    with pytest.raises(ValueError, match="zona horaria"):
        build_report(database=database, as_of=datetime(2026, 9, 1, 21, 0))


@pytest.mark.parametrize(
    "overrides",
    [
        {"activeInstrumentCount": 9},
        {"coveredInstrumentCount": 9},
        {"coveredInstrumentCount": 11},
        {"deepHistoryInstrumentCount": 11},
        {"currentDeepHistoryInstrumentCount": 11},
        {"historyEligibleInstrumentCount": 0},
        {"historyEligibleInstrumentCount": 10.5},
        {"maximumSourceGapDays": 8},
        {"maximumSourceGapDays": 0},
        {"asOf": "not-a-timestamp"},
        {"asOf": "2026-09-01T21:00:00"},
        {"asOf": ""},
    ],
)
def test_operational_readiness_rejects_inconsistent_or_unbounded_history_evidence(
    overrides,
) -> None:
    history = {**_complete_market_history(), **overrides}
    report = _readiness(market_history=history)
    assert report["ready"] is False
    assert "market_history_depth_insufficient" in report["blockers"]
    assert report["policy"]["productionEligibilityClaimed"] is False


def test_athena_readiness_exposes_read_only_pit_gap_drilldown(tmp_path: Path) -> None:
    from app.services.athena_readiness_service import build_readiness_report

    report = build_readiness_report(
        database=AthenaDatabase(tmp_path / "athena.db"),
        as_of=datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
    )
    drilldown = report["marketHistoryGapDiagnostics"]
    assert drilldown["endpoint"] == "/api/v1/readiness/market-history/gaps"
    assert drilldown["asOfParameter"] == "asOf"
    assert drilldown["readOnly"] is True
    assert drilldown["productionEvidenceClaimed"] is False
    assert report["operationalReadiness"]["ready"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligibleOutcomeCount", 2.5),
        ("forecastErrorCount", 2.5),
        ("missingForecastErrorCount", 0.5),
        ("horizonCount", 1.5),
    ],
)
def test_oos_gate_rejects_fractional_global_counts(field, value) -> None:
    learning = _complete_learning()
    learning["researchForecastErrorOos"][field] = value
    report = _readiness(learning=learning)
    assert report["ready"] is False
    assert "forecast_error_oos_measurement_incomplete" in report["blockers"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligibleOutcomeCount", 2.5),
        ("forecastErrorCount", 2.5),
        ("missingForecastErrorCount", 0.5),
    ],
)
def test_oos_gate_rejects_fractional_horizon_counts(field, value) -> None:
    learning = _complete_learning()
    learning["researchForecastErrorOos"]["horizons"]["604800"][field] = value
    report = _readiness(learning=learning)
    assert report["ready"] is False
    assert "forecast_error_oos_measurement_incomplete" in report["blockers"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("eventCount", 2.5),
        ("agreedEventCount", 2.5),
        ("conflictEventCount", 0.5),
        ("incompleteEventCount", 0.5),
        ("agreementCoverage", 1.01),
        ("independentProviderFamilies", ["Yahoo", " yahoo "]),
        ("independentProviderFamilies", ["yahoo", 123]),
        ("independentProviderFamilies", ["yahoo", " "]),
    ],
)
def test_corporate_action_gate_rejects_invalid_measured_evidence(field, value) -> None:
    evidence = _complete_corporate_actions()
    evidence[field] = value
    report = _readiness(corporate_actions=evidence)
    assert report["ready"] is False
    assert "corporate_actions_independent_reconciliation_pending" in report["blockers"]

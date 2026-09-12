from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.services.athena_readiness_service import build_operational_readiness
from scripts.athena_readiness_report import build_report


def _complete_market_history() -> dict[str, object]:
    return {
        "historyDepthReady": True,
        "sourceContinuityRequired": True,
        "historyEligibleInstrumentCount": 10,
        "deepHistoryInstrumentCount": 10,
        "deepHistoryCoverage": 1.0,
        "minimumHistoryDays": 365,
    }


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
    assert "external_market_cap_validation_required" in report["marketWeighting"][
        "blockers"
    ]
    assert report["instrumentTypes"]["listingCount"] == 0
    assert report["marketHistory"]["observationCount"] == 0
    assert report["marketHistory"]["instrumentCoverage"] == 0.0
    assert report["marketHistory"]["historyDepthReady"] is False
    assert (
        report["recommendationLearning"]["automaticModelMutation"]
        is False
    )

    readiness = report["operationalReadiness"]
    assert readiness["scope"] == (
        "operational_evidence_readiness_not_product_feature_completeness"
    )
    assert readiness["completionPercent"] == 0.0
    assert readiness["passedGateCount"] == 0
    assert readiness["totalGateCount"] == 5
    assert readiness["ready"] is False
    assert "global_market_universe_not_ready" in readiness["blockers"]
    assert "canonical_market_weighting_not_ready" in readiness["blockers"]
    assert "market_history_depth_insufficient" in readiness["blockers"]
    assert "research_outcome_oos_evidence_pending" in readiness["blockers"]
    assert "forecast_error_oos_measurement_incomplete" in readiness["blockers"]
    assert "external_market_cap_validation_required" in readiness["blockers"]
    assert readiness["policy"]["featureCompletenessClaimed"] is False
    assert readiness["policy"]["productionEligibilityClaimed"] is False
    assert readiness["policy"]["automaticTrading"] is False


def test_operational_readiness_reaches_100_only_when_all_gates_pass() -> None:
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history=_complete_market_history(),
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": 1.0,
            },
        },
    )

    assert report["completionPercent"] == 100.0
    assert report["passedGateCount"] == 5
    assert report["totalGateCount"] == 5
    assert report["ready"] is True
    assert report["blockers"] == []
    assert all(gate["passed"] is True for gate in report["gates"])
    assert report["policy"]["oneHundredPercentMeaning"] == (
        "all_current_operational_evidence_gates_passed_only"
    )
    assert report["policy"]["featureCompletenessClaimed"] is False


def test_operational_readiness_requires_full_forecast_error_coverage() -> None:
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history=_complete_market_history(),
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": 0.99,
            },
        },
    )

    assert report["completionPercent"] == 80.0
    assert report["ready"] is False
    assert report["blockers"] == [
        "forecast_error_oos_measurement_incomplete",
    ]


def test_operational_readiness_rejects_shallow_history() -> None:
    history = _complete_market_history()
    history["historyDepthReady"] = False
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history=history,
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": 1.0,
            },
        },
    )

    assert report["completionPercent"] == 80.0
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_legacy_30_percent_history_threshold() -> None:
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history={
            "historyDepthReady": True,
            "sourceContinuityRequired": True,
            "historyEligibleInstrumentCount": 10,
            "deepHistoryInstrumentCount": 3,
            "deepHistoryCoverage": 0.3,
            "minimumHistoryDays": 365,
        },
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": 1.0,
            },
        },
    )

    assert report["completionPercent"] == 80.0
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_fails_closed_when_final_history_evidence_is_missing() -> None:
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history={"historyDepthReady": True},
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": 1.0,
            },
        },
    )

    assert report["completionPercent"] == 80.0
    assert report["ready"] is False
    assert report["blockers"] == ["market_history_depth_insufficient"]


def test_operational_readiness_rejects_non_finite_forecast_coverage() -> None:
    report = build_operational_readiness(
        universe={"isGlobalReady": True},
        weighting={"ready": True, "blockers": []},
        market_history=_complete_market_history(),
        learning={
            "researchOutcomeOos": {
                "status": "research_outcome_oos_evidence_available",
            },
            "researchForecastErrorOos": {
                "status": "forecast_error_oos_evidence_available",
                "measurementCoverage": float("inf"),
            },
        },
    )

    assert report["completionPercent"] == 80.0
    assert report["ready"] is False
    assert report["blockers"] == ["forecast_error_oos_measurement_incomplete"]


def test_athena_readiness_report_requires_timezone_aware_as_of(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")

    with pytest.raises(ValueError, match="zona horaria"):
        build_report(
            database=database,
            as_of=datetime(2026, 9, 1, 21, 0),
        )

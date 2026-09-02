from datetime import datetime, timedelta, timezone

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository
from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)


CUT = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)


def _benchmark_evidence(due: datetime) -> dict[str, object]:
    entry_observed = CUT + timedelta(hours=1)
    exit_observed = due
    return {
        "status": "resolved",
        "benchmarkSymbol": "SPY",
        "benchmarkInstrumentId": 999,
        "entryPrice": 100.0,
        "exitPrice": 103.0,
        "benchmarkReturn": 0.03,
        "entryObservedAt": entry_observed.isoformat(),
        "exitObservedAt": exit_observed.isoformat(),
        "entryRetrievedAt": (entry_observed + timedelta(minutes=1)).isoformat(),
        "exitRetrievedAt": exit_observed.isoformat(),
        "entrySourceProvider": "test_benchmark",
        "exitSourceProvider": "test_benchmark",
        "policy": {"retrievalCutoff": "retrieved_at_not_after_evaluation_as_of"},
    }


def _setup_row(tmp_path, *, feature_value=0.08):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NMS",
            "instrumentType": "common_stock",
            "country": "United States",
            "regionKey": "america",
        }
    )
    repository = RecommendationShadowRepository(database=database)
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot={
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "market": {
                "technicalScore": 60.0,
                "riskScore": 30.0,
                "return20d": feature_value,
            },
            "fundamentals": {"coverageRatio": 1.0, "ratios": {}},
            "valuation": {"reportedAnnualPe": 25.0},
        },
        benchmark_symbol="SPY",
    )
    due = CUT + timedelta(days=7)
    repository.record_outcome(
        snapshot_id=snapshot_id,
        horizon_days=7,
        due_at=due,
        evaluated_at=due + timedelta(hours=1),
        exit_price=110.0,
        exit_observed_at=due,
        exit_retrieved_at=due,
        source_provider="test",
        benchmark_return=0.03,
        benchmark_evidence=_benchmark_evidence(due),
    )
    return database, snapshot_id


def test_non_finite_optional_feature_is_removed_from_calibration(tmp_path) -> None:
    database, _ = _setup_row(tmp_path, feature_value=float("nan"))

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=8),
        horizon_days=7,
        require_benchmark=True,
    )

    assert result["rowCount"] == 1
    assert result["rows"][0]["features"]["return20d"] is None
    assert result["policy"]["numericIntegrity"] == (
        "non_finite_values_never_enter_calibration"
    )


def test_non_finite_required_target_rejects_entire_calibration_row(tmp_path) -> None:
    database, snapshot_id = _setup_row(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_shadow_outcomes
            SET realized_return = ?
            WHERE snapshot_id = ? AND horizon_days = 7
            """,
            ("NaN", snapshot_id),
        )

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=8),
        horizon_days=7,
    )

    assert result["rowCount"] == 0
    assert result["rejectedNonFiniteTargetCount"] == 1

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository
from app.services.recommendation_shadow_calibration_dataset_service import (
    RecommendationShadowCalibrationDatasetService,
)


CUT = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
FEATURE_SCHEMA_VERSION = "shadow-evidence-v2"


def _setup(tmp_path):
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
    return database, repository, instrument_id


def _evidence() -> dict[str, object]:
    return {
        "status": "evidence_ready_for_calibration",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "market": {
            "technicalScore": 61.0,
            "riskScore": 30.0,
            "return20d": 0.08,
            "return60d": 0.15,
            "annualizedVolatility": 0.22,
            "maxDrawdown60d": -0.09,
        },
        "fundamentals": {
            "coverageRatio": 1.0,
            "ratios": {
                "revenueGrowth": 0.12,
                "netMargin": 0.24,
                "liabilitiesToAssets": 0.63,
            },
        },
        "valuation": {"reportedAnnualPe": 25.0},
    }


def _benchmark_evidence(due: datetime, benchmark_return: float) -> dict[str, object]:
    entry_observed = CUT + timedelta(hours=1)
    exit_observed = due + timedelta(hours=1)
    return {
        "status": "resolved",
        "benchmarkSymbol": "SPY",
        "benchmarkInstrumentId": 999,
        "entryPrice": 100.0,
        "exitPrice": 100.0 * (1.0 + benchmark_return),
        "benchmarkReturn": benchmark_return,
        "entryObservedAt": entry_observed.isoformat(),
        "exitObservedAt": exit_observed.isoformat(),
        "entryRetrievedAt": (entry_observed + timedelta(minutes=1)).isoformat(),
        "exitRetrievedAt": (exit_observed + timedelta(minutes=1)).isoformat(),
        "entrySourceProvider": "test_benchmark",
        "exitSourceProvider": "test_benchmark",
        "policy": {"retrievalCutoff": "retrieved_at_not_after_evaluation_as_of"},
    }


def _create_matured_snapshot(
    repository: RecommendationShadowRepository,
    *,
    instrument_id: int,
    schema: str = FEATURE_SCHEMA_VERSION,
    benchmark_return: float | None = 0.03,
) -> int:
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version=schema,
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot=_evidence(),
        benchmark_symbol="SPY" if benchmark_return is not None else None,
    )
    due = CUT + timedelta(days=7)
    repository.record_outcome(
        snapshot_id=snapshot_id,
        horizon_days=7,
        due_at=due,
        evaluated_at=due + timedelta(hours=2),
        exit_price=110.0,
        exit_observed_at=due + timedelta(hours=1),
        exit_retrieved_at=due + timedelta(hours=1, minutes=5),
        source_provider="test",
        benchmark_return=benchmark_return,
        benchmark_evidence=(
            _benchmark_evidence(due, benchmark_return)
            if benchmark_return is not None
            else None
        ),
    )
    return snapshot_id


def test_dataset_extracts_only_whitelisted_features_and_continuous_targets(tmp_path) -> None:
    database, repository, instrument_id = _setup(tmp_path)
    snapshot_id = _create_matured_snapshot(repository, instrument_id=instrument_id)

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=8),
        horizon_days=7,
        require_benchmark=True,
    )

    assert result["status"] == "shadow_calibration_dataset"
    assert result["advisoryStatus"] == "no_advice"
    assert result["rowCount"] == 1
    row = result["rows"][0]
    assert row["snapshotId"] == snapshot_id
    assert row["target"]["realizedReturn"] == pytest.approx(0.10)
    assert row["target"]["benchmarkReturn"] == pytest.approx(0.03)
    assert row["target"]["excessReturn"] == pytest.approx(0.07)
    assert row["features"] == {
        "technicalScore": 61.0,
        "riskScore": 30.0,
        "return20d": 0.08,
        "return60d": 0.15,
        "annualizedVolatility": 0.22,
        "maxDrawdown60d": -0.09,
        "fundamentalCoverageRatio": 1.0,
        "revenueGrowth": 0.12,
        "netMargin": 0.24,
        "liabilitiesToAssets": 0.63,
        "reportedAnnualPe": 25.0,
    }
    assert "action" not in row
    assert "conviction" not in row
    assert result["policy"]["actions"] == "not_assigned"
    assert result["policy"]["featureWeights"] == "not_assigned"


def test_dataset_excludes_outcomes_not_known_by_as_of(tmp_path) -> None:
    database, repository, instrument_id = _setup(tmp_path)
    _create_matured_snapshot(repository, instrument_id=instrument_id)

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=7, hours=1),
        horizon_days=7,
    )

    assert result["rowCount"] == 0


def test_dataset_requires_exact_feature_schema_version(tmp_path) -> None:
    database, repository, instrument_id = _setup(tmp_path)
    _create_matured_snapshot(
        repository,
        instrument_id=instrument_id,
        schema="legacy-shadow-v0",
    )

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=8),
    )

    assert result["rowCount"] == 0
    assert result["featureSchemaVersion"] == FEATURE_SCHEMA_VERSION


def test_dataset_can_require_frozen_benchmark_outcomes(tmp_path) -> None:
    database, repository, instrument_id = _setup(tmp_path)
    _create_matured_snapshot(
        repository,
        instrument_id=instrument_id,
        benchmark_return=None,
    )

    service = RecommendationShadowCalibrationDatasetService(database=database)
    unrestricted = service.build(as_of=CUT + timedelta(days=8))
    benchmark_only = service.build(
        as_of=CUT + timedelta(days=8),
        require_benchmark=True,
    )

    assert unrestricted["rowCount"] == 1
    assert benchmark_only["rowCount"] == 0


def test_dataset_fails_closed_on_snapshot_claiming_advice_readiness(tmp_path) -> None:
    database, repository, instrument_id = _setup(tmp_path)
    evidence = _evidence()
    evidence["recommendationCandidateReady"] = True
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot=evidence,
    )
    due = CUT + timedelta(days=7)
    repository.record_outcome(
        snapshot_id=snapshot_id,
        horizon_days=7,
        due_at=due,
        evaluated_at=due,
        exit_price=105.0,
        exit_observed_at=due,
        exit_retrieved_at=due,
        source_provider="test",
    )

    result = RecommendationShadowCalibrationDatasetService(database=database).build(
        as_of=CUT + timedelta(days=8)
    )

    assert result["rowCount"] == 0
    assert result["rejectedInvalidSnapshotCount"] == 1


def test_dataset_requires_timezone_aware_as_of(tmp_path) -> None:
    database, _, _ = _setup(tmp_path)
    service = RecommendationShadowCalibrationDatasetService(database=database)

    with pytest.raises(ValueError, match="zona horaria"):
        service.build(as_of=datetime(2026, 1, 10, 20, 0))

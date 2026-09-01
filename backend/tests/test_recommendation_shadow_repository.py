from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)


CUT = datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)


def _repository(tmp_path) -> tuple[RecommendationShadowRepository, int]:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert(
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "exchangeShortName": "NMS",
            "country": "United States",
            "regionKey": "america",
        }
    )
    return RecommendationShadowRepository(database=database), instrument_id


def test_shadow_snapshot_has_no_advisory_columns_and_preserves_evidence(tmp_path) -> None:
    repository, instrument_id = _repository(tmp_path)
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="aapl",
        data_cutoff_at=CUT,
        captured_at=CUT + timedelta(minutes=5),
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=200.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot={"market": {"technicalScore": 61.0}},
        benchmark_symbol="SPY",
    )

    row = repository.get_snapshot(snapshot_id)
    assert row is not None
    assert row["symbol"] == "AAPL"
    assert row["benchmark_symbol"] == "SPY"
    assert row["evidence_snapshot"]["market"]["technicalScore"] == 61.0
    assert "action" not in row
    assert "score" not in row
    assert "conviction" not in row


def test_shadow_snapshot_rejects_future_entry_information(tmp_path) -> None:
    repository, instrument_id = _repository(tmp_path)

    with pytest.raises(ValueError, match="entry_retrieved_at"):
        repository.create_snapshot(
            instrument_id=instrument_id,
            symbol="AAPL",
            data_cutoff_at=CUT,
            captured_at=CUT + timedelta(minutes=1),
            feature_schema_version="shadow-evidence-v1",
            evidence_status="evidence_ready_for_calibration",
            entry_price=200.0,
            entry_observed_at=CUT - timedelta(hours=1),
            entry_retrieved_at=CUT + timedelta(seconds=1),
            evidence_snapshot={},
        )


def test_shadow_outcome_computes_return_and_enforces_maturity(tmp_path) -> None:
    repository, instrument_id = _repository(tmp_path)
    snapshot_id = repository.create_snapshot(
        instrument_id=instrument_id,
        symbol="AAPL",
        data_cutoff_at=CUT,
        captured_at=CUT,
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=200.0,
        entry_observed_at=CUT - timedelta(hours=1),
        entry_retrieved_at=CUT - timedelta(minutes=30),
        evidence_snapshot={},
    )
    due = CUT + timedelta(days=7)

    with pytest.raises(ValueError, match="anterior a due_at"):
        repository.record_outcome(
            snapshot_id=snapshot_id,
            horizon_days=7,
            due_at=due,
            evaluated_at=due - timedelta(seconds=1),
            exit_price=220.0,
            exit_observed_at=due,
            exit_retrieved_at=due,
            source_provider="test",
        )

    repository.record_outcome(
        snapshot_id=snapshot_id,
        horizon_days=7,
        due_at=due,
        evaluated_at=due + timedelta(hours=1),
        exit_price=220.0,
        exit_observed_at=due,
        exit_retrieved_at=due + timedelta(minutes=30),
        source_provider="test",
        benchmark_return=0.03,
    )
    outcomes = repository.list_outcomes(snapshot_id)
    assert len(outcomes) == 1
    assert outcomes[0]["realized_return"] == pytest.approx(0.10)
    assert outcomes[0]["excess_return"] == pytest.approx(0.07)

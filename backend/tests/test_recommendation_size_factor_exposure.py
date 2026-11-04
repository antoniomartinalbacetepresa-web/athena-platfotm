from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_size_factor_exposure_repository import RecommendationSizeFactorExposureRepository
from app.services.recommendation_size_factor_exposure_service import RecommendationSizeFactorExposureService


UTC = timezone.utc
AS_OF = datetime(2026, 1, 31, tzinfo=UTC)


def seeded_database(tmp_path, *, count: int = 20, include_future_revision: bool = False) -> AthenaDatabase:
    db = AthenaDatabase(tmp_path / "athena.db")
    db.initialize()
    with db.connect() as connection:
        for instrument_id in range(1, count + 1):
            connection.execute(
                """INSERT INTO instruments
                   (id, symbol, company_name, instrument_type, is_active)
                   VALUES (?, ?, ?, 'equity', 1)""",
                (instrument_id, f"S{instrument_id}", f"Company {instrument_id}"),
            )
            connection.execute(
                """INSERT INTO market_observations
                   (instrument_id, observed_at, close, market_cap_usd,
                    source_provider, retrieved_at)
                   VALUES (?, ?, ?, ?, 'yahoo', ?)""",
                (
                    instrument_id,
                    (AS_OF - timedelta(days=2)).isoformat(),
                    100.0,
                    float(instrument_id) * 1_000_000_000.0,
                    (AS_OF - timedelta(days=1)).isoformat(),
                ),
            )
        if include_future_revision:
            connection.execute(
                """INSERT INTO market_observations
                   (instrument_id, observed_at, close, market_cap_usd,
                    source_provider, retrieved_at)
                   VALUES (1, ?, 100.0, 999000000000.0, 'yahoo', ?)""",
                ((AS_OF - timedelta(hours=1)).isoformat(), (AS_OF + timedelta(days=1)).isoformat()),
            )
    return db


def test_size_factor_is_bounded_cross_sectional_and_pit(tmp_path) -> None:
    db = seeded_database(tmp_path, include_future_revision=True)
    service = RecommendationSizeFactorExposureService(database=db)

    smallest = service.evaluate(instrument_id=1, source_provider="yahoo", as_of=AS_OF)
    largest = service.evaluate(instrument_id=20, source_provider="yahoo", as_of=AS_OF)

    assert smallest["factors"]["size"] == pytest.approx(1.0)
    assert largest["factors"]["size"] == pytest.approx(-1.0)
    assert smallest["marketCapUsd"] == 1_000_000_000.0
    assert smallest["universeCount"] == 20
    assert smallest["advisoryStatus"] == "no_advice"
    assert smallest["productionEligible"] is False
    assert smallest["isWeightingReady"] is False
    assert smallest["policy"]["automaticTrading"] is False
    assert smallest["policy"]["thresholds"] == "not_calibrated"
    assert len(smallest["factorExposureKey"]) == 64


def test_size_factor_fails_closed_on_insufficient_universe_and_fmp(tmp_path) -> None:
    db = seeded_database(tmp_path, count=19)
    service = RecommendationSizeFactorExposureService(database=db)
    with pytest.raises(ValueError, match="20 instrumentos"):
        service.evaluate(instrument_id=1, source_provider="yahoo", as_of=AS_OF)
    with pytest.raises(ValueError, match="FMP"):
        service.evaluate(instrument_id=1, source_provider="FinancialModelingPrep", as_of=AS_OF)


def test_size_factor_repository_is_idempotent_and_tamper_evident(tmp_path) -> None:
    db = seeded_database(tmp_path)
    service = RecommendationSizeFactorExposureService(database=db)
    repository = RecommendationSizeFactorExposureRepository(database=db, service=service)
    artifact = service.evaluate(instrument_id=5, source_provider="yahoo", as_of=AS_OF)

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    assert first["id"] == second["id"]

    with db.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_size_factor_exposure_artifacts WHERE factor_exposure_key = ?",
            (artifact["factorExposureKey"],),
        ).fetchone()
        tampered = json.loads(row["artifact_json"])
        tampered["factors"]["size"] = 0.123
        connection.execute(
            "UPDATE athena_size_factor_exposure_artifacts SET artifact_json = ? WHERE factor_exposure_key = ?",
            (json.dumps(tampered), artifact["factorExposureKey"]),
        )

    with pytest.raises(ValueError, match="factorExposureKey"):
        repository.get(factor_exposure_key=artifact["factorExposureKey"])

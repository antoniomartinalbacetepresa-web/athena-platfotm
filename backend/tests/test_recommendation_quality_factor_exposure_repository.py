from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_quality_factor_exposure_repository import (
    RecommendationQualityFactorExposureRepository,
)
from app.services.recommendation_quality_factor_exposure_service import (
    RecommendationQualityFactorExposureService,
)
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolution


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Instruments:
    def list_active(self):
        return [{"id": i, "instrument_type": "common_stock", "is_primary_listing": 1} for i in range(1, 21)]


class Ciks:
    def resolve(self, *, instrument_id: int):
        return SecInstrumentCikResolution(
            instrument_id=instrument_id,
            issuer_id=1000 + instrument_id,
            cik=str(instrument_id).zfill(10),
            issuer_name=f"Issuer {instrument_id}",
            link_confidence=1.0,
            external_id_confidence=1.0,
            evidence_source="test",
            resolution_method="test",
            identity_key="a" * 64,
        )


class Margins:
    def evaluate(self, *, instrument_id: int, as_of: datetime):
        return {
            "status": "resolved",
            "evidenceKey": f"{instrument_id % 16:x}" * 64,
            "operatingMargin": instrument_id / 100.0,
        }


def _service() -> RecommendationQualityFactorExposureService:
    return RecommendationQualityFactorExposureService(
        instrument_repository=Instruments(),
        cik_resolver=Ciks(),
        operating_margin_service=Margins(),
    )


def test_quality_repository_is_idempotent_and_detects_sqlite_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    service = _service()
    repository = RecommendationQualityFactorExposureRepository(database=database, service=service)
    artifact = service.evaluate(instrument_id=10, as_of=AS_OF)

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    assert first["id"] == second["id"]
    assert first["artifact"]["factorExposureKey"] == artifact["factorExposureKey"]

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_quality_factor_exposure_artifacts SET universe_fingerprint = ? WHERE factor_exposure_key = ?",
            ("f" * 64, artifact["factorExposureKey"]),
        )

    with pytest.raises(ValueError, match="universe_fingerprint"):
        repository.get(factor_exposure_key=str(artifact["factorExposureKey"]))


def test_quality_repository_rejects_tampered_artifact_before_write(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    service = _service()
    repository = RecommendationQualityFactorExposureRepository(database=database, service=service)
    artifact = service.evaluate(instrument_id=10, as_of=AS_OF)
    artifact["factors"]["quality"] = 0.99
    with pytest.raises(ValueError, match="factorExposureKey"):
        repository.append(artifact=artifact)

import json
import sqlite3

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_value_factor_exposure_repository import (
    RecommendationValueFactorExposureRepository,
)
from app.services.recommendation_value_factor_exposure_service import (
    RecommendationValueFactorExposureService,
)


def artifact():
    payload = {
        "module": "pit_value_factor_exposure",
        "instrumentId": 42,
        "asOf": "2026-03-01T12:00:00+00:00",
        "availableAt": "2026-03-01T12:00:00+00:00",
        "bookToMarket": 0.5,
        "bookToMarketEvidenceKey": "a" * 64,
        "issuerId": 7,
        "cik": "0000123456",
        "universeCount": 20,
        "universeFingerprint": "b" * 64,
        "factors": {"value": 0.25},
        "provenance": {
            "universeRule": "active_primary_common_stock_unique_canonical_issuer_unique_sec_cik_resolved_book_to_market",
            "issuerDeduplication": "issuers_with_multiple_primary_listings_excluded",
            "targetBookToMarketEvidenceKey": "a" * 64,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "temporal": "all_upstream_evidence_point_in_time_at_as_of",
            "estimator": "cross_sectional_book_to_market_rank_high_positive_low_negative_bounded_minus1_plus1",
            "universe": "active_primary_common_stock_unique_issuer_sec_pit_only",
            "thresholds": "not_calibrated",
            "missingEvidence": "excluded_never_imputed",
            "statisticalIndependence": "not_claimed",
            "purpose": "factor_risk_diagnostic_only",
        },
    }
    payload["factorExposureKey"] = RecommendationValueFactorExposureService._key(payload)
    return payload


def test_value_repository_is_idempotent_and_preserves_sealed_identity(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationValueFactorExposureRepository(database=database)
    item = artifact()

    first = repo.append(artifact=item)
    second = repo.append(artifact=item)
    loaded = repo.get(factor_exposure_key=item["factorExposureKey"])

    assert loaded is not None
    assert first["id"] == second["id"] == loaded["id"]
    assert loaded["artifact"]["factors"] == {"value": 0.25}
    assert loaded["book_to_market_evidence_key"] == "a" * 64
    assert loaded["universe_fingerprint"] == "b" * 64


def test_value_repository_detects_direct_sqlite_artifact_tampering(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationValueFactorExposureRepository(database=database)
    item = artifact()
    repo.append(artifact=item)

    with sqlite3.connect(database.database_path) as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_value_factor_exposure_artifacts WHERE factor_exposure_key = ?",
            (item["factorExposureKey"],),
        ).fetchone()
        payload = json.loads(row[0])
        payload["factors"]["value"] = 0.75
        connection.execute(
            "UPDATE athena_value_factor_exposure_artifacts SET artifact_json = ? WHERE factor_exposure_key = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), item["factorExposureKey"]),
        )

    with pytest.raises(ValueError, match="factorExposureKey"):
        repo.get(factor_exposure_key=item["factorExposureKey"])


def test_value_repository_rejects_invalid_key_and_unsafe_artifact(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationValueFactorExposureRepository(database=database)
    with pytest.raises(ValueError, match="SHA-256"):
        repo.get(factor_exposure_key="bad")

    unsafe = artifact()
    unsafe["productionEligible"] = True
    with pytest.raises(ValueError, match="producción"):
        repo.append(artifact=unsafe)

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_live_uncertainty_repository import (
    RecommendationShadowLiveUncertaintyRepository,
)
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository


def _database_with_candidate(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO instruments (symbol, company_name) VALUES (?, ?)",
            ("TEST", "Test Company"),
        )
        instrument_id = int(cursor.lastrowid)
    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    snapshot_id = RecommendationShadowRepository(database).create_snapshot(
        instrument_id=instrument_id,
        symbol="TEST",
        data_cutoff_at=cutoff,
        captured_at=cutoff,
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=cutoff,
        entry_retrieved_at=cutoff,
        evidence_snapshot={"productionEligible": False},
        benchmark_symbol="SPY",
    )
    artifact = {"candidateFingerprint": "c" * 64}
    candidate_id = RecommendationShadowLiveCandidateRepository(database).save(
        snapshot_id=snapshot_id,
        candidate_fingerprint="c" * 64,
        confirmation_fingerprint="d" * 64,
        artifact_version="shadow-live-candidate-v1",
        artifact=artifact,
    )
    return database, candidate_id


def _uncertainty():
    return {
        "artifactVersion": "shadow-live-uncertainty-v1",
        "candidateId": 1,
        "candidateFingerprint": "c" * 64,
        "status": "shadow_live_empirical_uncertainty_pending",
        "horizons": {"7": {"scenarios": None}},
    }


def test_repository_persists_reloads_and_is_idempotent(tmp_path):
    database, candidate_id = _database_with_candidate(tmp_path)
    repository = RecommendationShadowLiveUncertaintyRepository(database)
    artifact = _uncertainty()
    artifact["candidateId"] = candidate_id

    first = repository.save(
        candidate_id=candidate_id,
        candidate_fingerprint="c" * 64,
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    second = repository.save(
        candidate_id=candidate_id,
        candidate_fingerprint="c" * 64,
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    loaded = repository.get(first)

    assert first == second
    assert loaded is not None
    assert loaded["artifact"] == artifact
    assert len(loaded["uncertainty_fingerprint"]) == 64
    assert repository.get_for_candidate(candidate_id)["id"] == first


def test_repository_rejects_rewriting_candidate_uncertainty(tmp_path):
    database, candidate_id = _database_with_candidate(tmp_path)
    repository = RecommendationShadowLiveUncertaintyRepository(database)
    artifact = _uncertainty()
    artifact["candidateId"] = candidate_id
    repository.save(
        candidate_id=candidate_id,
        candidate_fingerprint="c" * 64,
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    changed = dict(artifact)
    changed["status"] = "changed_after_the_fact"

    with pytest.raises(ValueError, match="sellada con contenido distinto"):
        repository.save(
            candidate_id=candidate_id,
            candidate_fingerprint="c" * 64,
            artifact_version=artifact["artifactVersion"],
            artifact=changed,
        )


def test_repository_detects_manual_database_tampering(tmp_path):
    database, candidate_id = _database_with_candidate(tmp_path)
    repository = RecommendationShadowLiveUncertaintyRepository(database)
    artifact = _uncertainty()
    artifact["candidateId"] = candidate_id
    uncertainty_id = repository.save(
        candidate_id=candidate_id,
        candidate_fingerprint="c" * 64,
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    tampered = dict(artifact)
    tampered["status"] = "tampered"
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_shadow_live_uncertainty
            SET artifact_json = ?
            WHERE id = ?
            """,
            (json.dumps(tampered, sort_keys=True, separators=(",", ":")), uncertainty_id),
        )

    with pytest.raises(ValueError, match="fue alterada"):
        repository.get(uncertainty_id)


def test_repository_rejects_non_finite_artifact(tmp_path):
    database, candidate_id = _database_with_candidate(tmp_path)
    repository = RecommendationShadowLiveUncertaintyRepository(database)
    artifact = _uncertainty()
    artifact["candidateId"] = candidate_id
    artifact["bad"] = float("nan")

    with pytest.raises(ValueError, match="finito"):
        repository.save(
            candidate_id=candidate_id,
            candidate_fingerprint="c" * 64,
            artifact_version=artifact["artifactVersion"],
            artifact=artifact,
        )

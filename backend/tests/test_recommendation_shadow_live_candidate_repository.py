from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)


def _database_with_snapshot(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO instruments (symbol, company_name) VALUES (?, ?)",
            ("TEST", "Test Company"),
        )
        instrument_id = int(cursor.lastrowid)
    shadow = RecommendationShadowRepository(database)
    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    snapshot_id = shadow.create_snapshot(
        instrument_id=instrument_id,
        symbol="TEST",
        data_cutoff_at=cutoff,
        captured_at=cutoff,
        feature_schema_version="shadow-evidence-v1",
        evidence_status="evidence_ready_for_calibration",
        entry_price=100.0,
        entry_observed_at=cutoff,
        entry_retrieved_at=cutoff,
        evidence_snapshot={
            "productionEligible": False,
            "recommendationCandidateReady": False,
        },
        benchmark_symbol="SPY",
    )
    return database, snapshot_id


def _artifact():
    return {
        "status": "shadow_live_candidate_inferred",
        "artifactVersion": "shadow-live-candidate-v1",
        "candidateFingerprint": "c" * 64,
        "confirmationEvidenceFingerprint": "d" * 64,
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "advisoryStatus": "no_advice",
        "action": None,
        "score": None,
        "conviction": None,
    }


def test_repository_persists_and_reloads_candidate_json(tmp_path):
    database, snapshot_id = _database_with_snapshot(tmp_path)
    repository = RecommendationShadowLiveCandidateRepository(database)
    artifact = _artifact()

    candidate_id = repository.save(
        snapshot_id=snapshot_id,
        candidate_fingerprint=artifact["candidateFingerprint"],
        confirmation_fingerprint=artifact["confirmationEvidenceFingerprint"],
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    loaded = repository.get(candidate_id)

    assert loaded is not None
    assert loaded["snapshot_id"] == snapshot_id
    assert loaded["artifact"] == artifact
    assert repository.get_by_fingerprint("c" * 64)["id"] == candidate_id
    assert repository.list_for_snapshot(snapshot_id)[0]["id"] == candidate_id
    assert repository.list_all()[0]["id"] == candidate_id


def test_repository_is_idempotent_for_identical_fingerprint_and_content(tmp_path):
    database, snapshot_id = _database_with_snapshot(tmp_path)
    repository = RecommendationShadowLiveCandidateRepository(database)
    artifact = _artifact()
    kwargs = {
        "snapshot_id": snapshot_id,
        "candidate_fingerprint": artifact["candidateFingerprint"],
        "confirmation_fingerprint": artifact["confirmationEvidenceFingerprint"],
        "artifact_version": artifact["artifactVersion"],
        "artifact": artifact,
    }

    first = repository.save(**kwargs)
    second = repository.save(**kwargs)

    assert first == second
    assert len(repository.list_for_snapshot(snapshot_id)) == 1
    assert len(repository.list_all()) == 1


def test_repository_rejects_same_fingerprint_with_different_content(tmp_path):
    database, snapshot_id = _database_with_snapshot(tmp_path)
    repository = RecommendationShadowLiveCandidateRepository(database)
    artifact = _artifact()
    repository.save(
        snapshot_id=snapshot_id,
        candidate_fingerprint=artifact["candidateFingerprint"],
        confirmation_fingerprint=artifact["confirmationEvidenceFingerprint"],
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    changed = dict(artifact)
    changed["status"] = "changed"

    with pytest.raises(ValueError, match="contenido distinto"):
        repository.save(
            snapshot_id=snapshot_id,
            candidate_fingerprint=artifact["candidateFingerprint"],
            confirmation_fingerprint=artifact["confirmationEvidenceFingerprint"],
            artifact_version=artifact["artifactVersion"],
            artifact=changed,
        )


def test_repository_rejects_second_candidate_for_same_snapshot_and_confirmation(tmp_path):
    database, snapshot_id = _database_with_snapshot(tmp_path)
    repository = RecommendationShadowLiveCandidateRepository(database)
    artifact = _artifact()
    repository.save(
        snapshot_id=snapshot_id,
        candidate_fingerprint=artifact["candidateFingerprint"],
        confirmation_fingerprint=artifact["confirmationEvidenceFingerprint"],
        artifact_version=artifact["artifactVersion"],
        artifact=artifact,
    )
    second = dict(artifact)
    second["candidateFingerprint"] = "e" * 64

    with pytest.raises(ValueError, match="mismo snapshot"):
        repository.save(
            snapshot_id=snapshot_id,
            candidate_fingerprint=second["candidateFingerprint"],
            confirmation_fingerprint=second["confirmationEvidenceFingerprint"],
            artifact_version=second["artifactVersion"],
            artifact=second,
        )


def test_repository_foreign_key_rejects_unknown_snapshot(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationShadowLiveCandidateRepository(database)
    artifact = _artifact()

    with pytest.raises(Exception):
        repository.save(
            snapshot_id=999,
            candidate_fingerprint=artifact["candidateFingerprint"],
            confirmation_fingerprint=artifact["confirmationEvidenceFingerprint"],
            artifact_version=artifact["artifactVersion"],
            artifact=artifact,
        )

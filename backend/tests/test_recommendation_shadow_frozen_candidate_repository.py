from __future__ import annotations

import copy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_frozen_candidate_repository import (
    RecommendationShadowFrozenCandidateRepository,
)


def _repository(tmp_path):
    return RecommendationShadowFrozenCandidateRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def _bundle(*, fingerprint_char: str = "a"):
    fingerprint = fingerprint_char * 64
    return {
        "status": "shadow_research_gated_model_frozen",
        "bundleVersion": "shadow-gated-freeze-v2",
        "bundleFingerprint": fingerprint,
        "modelFingerprint": "b" * 64,
        "researchGateFingerprint": "c" * 64,
        "protocolSelectionFingerprint": "d" * 64,
        "sourceWalkForwardFingerprint": "e" * 64,
        "horizonDays": 30,
        "researchCutoff": "2026-01-01T00:00:00+00:00",
        "ridgeLambda": 1.0,
        "frozenModel": {"fingerprint": "b" * 64},
        "researchGateEvidence": {"researchStageEligible": True},
        "protocolSelectionEvidence": {"selectedRidgeLambda": 1.0},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_save_is_idempotent_and_preserves_complete_bundle(tmp_path):
    repository = _repository(tmp_path)
    bundle = _bundle()

    first_id = repository.save(bundle=bundle)
    second_id = repository.save(bundle=bundle)

    assert first_id == second_id
    row = repository.get_by_fingerprint(bundle["bundleFingerprint"])
    assert row is not None
    assert row["horizon_days"] == 30
    assert row["ridge_lambda"] == 1.0
    assert row["bundle"] == bundle
    assert "action" not in row
    assert "score" not in row
    assert "conviction" not in row


def test_same_bundle_fingerprint_cannot_hide_different_content(tmp_path):
    repository = _repository(tmp_path)
    bundle = _bundle()
    repository.save(bundle=bundle)
    changed = copy.deepcopy(bundle)
    changed["ridgeLambda"] = 10.0

    with pytest.raises(ValueError, match="contenido diferente"):
        repository.save(bundle=changed)


def test_repository_rejects_production_or_advisory_artifacts(tmp_path):
    repository = _repository(tmp_path)
    production = _bundle()
    production["productionEligible"] = True
    with pytest.raises(ValueError, match="productionEligible"):
        repository.save(bundle=production)

    advisory = _bundle()
    advisory["advisoryStatus"] = "buy"
    with pytest.raises(ValueError, match="no_advice"):
        repository.save(bundle=advisory)


def test_repository_rejects_invalid_fingerprints_and_naive_cutoff(tmp_path):
    repository = _repository(tmp_path)
    invalid = _bundle()
    invalid["bundleFingerprint"] = "not-sha256"
    with pytest.raises(ValueError, match="SHA-256"):
        repository.save(bundle=invalid)

    naive = _bundle(fingerprint_char="f")
    naive["researchCutoff"] = "2026-01-01T00:00:00"
    with pytest.raises(ValueError, match="zona horaria"):
        repository.save(bundle=naive)


def test_list_for_horizon_is_ordered_by_research_cutoff(tmp_path):
    repository = _repository(tmp_path)
    later = _bundle(fingerprint_char="1")
    later["researchCutoff"] = "2026-02-01T00:00:00+00:00"
    earlier = _bundle(fingerprint_char="2")
    earlier["researchCutoff"] = "2026-01-01T00:00:00+00:00"
    other = _bundle(fingerprint_char="3")
    other["horizonDays"] = 90

    repository.save(bundle=later)
    repository.save(bundle=earlier)
    repository.save(bundle=other)

    rows = repository.list_for_horizon(horizon_days=30)

    assert [row["bundle_fingerprint"] for row in rows] == [
        earlier["bundleFingerprint"],
        later["bundleFingerprint"],
    ]

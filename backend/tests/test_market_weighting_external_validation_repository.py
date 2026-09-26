from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.market_weighting_external_validation_repository import (
    MarketWeightingExternalValidationRepository,
)


_EVIDENCE_A = "a" * 64
_EVIDENCE_B = "b" * 64


def _repository(tmp_path) -> MarketWeightingExternalValidationRepository:
    database = AthenaDatabase(tmp_path / "athena.db")
    return MarketWeightingExternalValidationRepository(database=database)


def test_registers_append_only_human_validation_bound_to_exact_evidence(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = repository.register(
        identity_evidence_fingerprint=_EVIDENCE_A,
        reference="independent-market-cap-review-2026-09-07",
        reviewer_id="operator-1",
        human_review_confirmed=True,
    )

    assert artifact["validationPassed"] is True
    assert artifact["identityEvidenceFingerprint"] == _EVIDENCE_A
    assert artifact["humanReviewConfirmed"] is True
    assert artifact["automaticWeightingActivation"] is False
    assert artifact["validationMode"] == "offline_local_operator"

    loaded = repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE_A,
    )
    assert loaded == artifact
    assert repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE_B,
    ) is None


def test_rejects_validation_without_explicit_human_review(tmp_path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="human_review_confirmed"):
        repository.register(
            identity_evidence_fingerprint=_EVIDENCE_A,
            reference="independent-review",
            reviewer_id="operator-1",
            human_review_confirmed=False,
        )


def test_rejects_missing_reference_reviewer_and_invalid_fingerprint(tmp_path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="reference"):
        repository.register(
            identity_evidence_fingerprint=_EVIDENCE_A,
            reference="",
            reviewer_id="operator-1",
            human_review_confirmed=True,
        )
    with pytest.raises(ValueError, match="reviewer_id"):
        repository.register(
            identity_evidence_fingerprint=_EVIDENCE_A,
            reference="review",
            reviewer_id="",
            human_review_confirmed=True,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        repository.register(
            identity_evidence_fingerprint="not-a-fingerprint",
            reference="review",
            reviewer_id="operator-1",
            human_review_confirmed=True,
        )


def test_pit_lookup_requires_validation_and_persistence_known_by_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = MarketWeightingExternalValidationRepository(database=database)
    artifact = repository.register(
        identity_evidence_fingerprint=_EVIDENCE_A,
        reference="independent-review",
        reviewer_id="operator-1",
        human_review_confirmed=True,
    )
    created_at = datetime.fromisoformat(artifact["createdAt"].replace("Z", "+00:00"))

    assert repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE_A,
        as_of=created_at - timedelta(microseconds=1),
    ) is None
    assert repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE_A,
        as_of=created_at + timedelta(microseconds=1),
    ) is not None


def test_rejects_future_validation_time(tmp_path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="futuro"):
        repository.register(
            identity_evidence_fingerprint=_EVIDENCE_A,
            reference="independent-review",
            reviewer_id="operator-1",
            human_review_confirmed=True,
            validated_at=datetime.now(timezone.utc) + timedelta(days=1),
        )


def test_detects_tampered_persisted_validation(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = MarketWeightingExternalValidationRepository(database=database)
    repository.register(
        identity_evidence_fingerprint=_EVIDENCE_A,
        reference="independent-review",
        reviewer_id="operator-1",
        human_review_confirmed=True,
    )

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_market_weighting_external_validations
            SET reference = 'tampered-review'
            WHERE identity_evidence_fingerprint = ?
            """,
            (_EVIDENCE_A,),
        )

    with pytest.raises(RuntimeError, match="no coincide"):
        repository.get_latest_for_evidence(
            identity_evidence_fingerprint=_EVIDENCE_A,
        )

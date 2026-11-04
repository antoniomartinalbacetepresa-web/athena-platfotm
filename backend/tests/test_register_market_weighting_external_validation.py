from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.market_weighting_external_validation_repository import (
    MarketWeightingExternalValidationRepository,
)
from scripts import register_market_weighting_external_validation as registration_script


_EVIDENCE = "d" * 64


class _FakeReadinessService:
    blockers: tuple[str, ...] = ()

    def __init__(self, *, database=None) -> None:
        self.database = database

    def get_report(self):
        return SimpleNamespace(
            blockers=self.blockers,
            identity_evidence_fingerprint=_EVIDENCE,
        )


def test_offline_registration_refuses_unresolved_structural_blockers(
    tmp_path,
    monkeypatch,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _FakeReadinessService.blockers = (
        "insufficient_canonical_identity_market_cap_coverage",
        "external_market_cap_validation_required",
    )
    monkeypatch.setattr(
        registration_script,
        "MarketWeightingReadinessService",
        _FakeReadinessService,
    )

    with pytest.raises(RuntimeError, match="bloqueos estructurales"):
        registration_script.register_validation(
            reference="independent-review",
            reviewer_id="operator-1",
            human_review_confirmed=True,
            database=database,
        )

    repository = MarketWeightingExternalValidationRepository(database=database)
    assert repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE,
    ) is None


def test_offline_registration_persists_only_exact_reviewed_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _FakeReadinessService.blockers = ("external_market_cap_validation_required",)
    monkeypatch.setattr(
        registration_script,
        "MarketWeightingReadinessService",
        _FakeReadinessService,
    )

    artifact = registration_script.register_validation(
        reference="independent-review",
        reviewer_id="operator-1",
        human_review_confirmed=True,
        database=database,
    )

    assert artifact["identityEvidenceFingerprint"] == _EVIDENCE
    assert artifact["validationPassed"] is True
    assert artifact["automaticWeightingActivation"] is False
    assert artifact["validationMode"] == "offline_local_operator"

    repository = MarketWeightingExternalValidationRepository(database=database)
    persisted = repository.get_latest_for_evidence(
        identity_evidence_fingerprint=_EVIDENCE,
    )
    assert persisted == artifact


def test_offline_registration_still_requires_human_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    _FakeReadinessService.blockers = ("external_market_cap_validation_required",)
    monkeypatch.setattr(
        registration_script,
        "MarketWeightingReadinessService",
        _FakeReadinessService,
    )

    with pytest.raises(ValueError, match="human_review_confirmed"):
        registration_script.register_validation(
            reference="independent-review",
            reviewer_id="operator-1",
            human_review_confirmed=False,
            database=database,
        )

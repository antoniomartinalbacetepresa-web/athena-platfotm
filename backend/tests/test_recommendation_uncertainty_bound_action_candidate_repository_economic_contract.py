from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_uncertainty_bound_action_candidate_repository import (
    RecommendationUncertaintyBoundActionCandidateRepository,
)


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _artifact() -> dict:
    core = {
        "artifactVersion": "athena-uncertainty-bound-action-candidate-v1",
        "validatedActionCandidateFingerprint": "1" * 64,
        "actionUncertaintyEvidenceFingerprint": "2" * 64,
        "actionPromotionDecisionId": "decision-001",
        "actionPromotionDecisionFingerprint": "3" * 64,
        "economicContractFingerprint": "4" * 64,
        "candidateFingerprint": "5" * 64,
        "instrumentId": 101,
        "symbol": "AAA",
        "asOf": datetime(2026, 9, 1, 12, tzinfo=timezone.utc).isoformat(),
        "horizonDays": 30,
        "modelFingerprint": "6" * 64,
        "policyState": "flat",
        "policyFingerprint": "7" * 64,
        "portfolioPolicyStateFingerprint": "8" * 64,
        "action": "buy",
    }
    return {
        "status": "uncertainty_bound_action_candidate_non_advisory",
        **core,
        "uncertaintyBoundActionCandidateFingerprint": _fingerprint(core),
        "uncertaintyBoundActionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def test_repository_seals_and_reads_action_with_bound_economic_contract(tmp_path):
    repository = RecommendationUncertaintyBoundActionCandidateRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )
    artifact = _artifact()

    record = repository.seal(artifact=artifact)
    loaded = repository.get(
        candidate_fingerprint=artifact["uncertaintyBoundActionCandidateFingerprint"]
    )

    assert loaded is not None
    assert repository.validate_record(loaded) is loaded
    assert loaded["artifact"]["economicContractFingerprint"] == "4" * 64
    assert loaded["artifact"]["advisoryStatus"] == "no_advice"
    assert loaded["artifact"]["productionEligible"] is False
    assert loaded["artifact"]["allocationEligible"] is False
    assert loaded["artifact"]["automaticTrading"] is False
    assert record["record_fingerprint"] == loaded["record_fingerprint"]


def test_repository_rejects_economic_contract_substitution_without_resigning(tmp_path):
    repository = RecommendationUncertaintyBoundActionCandidateRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )
    tampered = copy.deepcopy(_artifact())
    tampered["economicContractFingerprint"] = "9" * 64

    with pytest.raises(ValueError, match="modificado"):
        repository.seal(artifact=tampered)


def test_repository_rejects_malformed_economic_contract_fingerprint(tmp_path):
    repository = RecommendationUncertaintyBoundActionCandidateRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )
    malformed = _artifact()
    core_keys = (
        "artifactVersion",
        "validatedActionCandidateFingerprint",
        "actionUncertaintyEvidenceFingerprint",
        "actionPromotionDecisionId",
        "actionPromotionDecisionFingerprint",
        "economicContractFingerprint",
        "candidateFingerprint",
        "instrumentId",
        "symbol",
        "asOf",
        "horizonDays",
        "modelFingerprint",
        "policyState",
        "policyFingerprint",
        "portfolioPolicyStateFingerprint",
        "action",
    )
    malformed["economicContractFingerprint"] = "not-a-sha"
    malformed["uncertaintyBoundActionCandidateFingerprint"] = _fingerprint(
        {key: malformed.get(key) for key in core_keys}
    )

    with pytest.raises(ValueError, match="economicContractFingerprint"):
        repository.seal(artifact=malformed)

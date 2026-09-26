from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.repositories.recommendation_portfolio_owner_scoped_evidence import (
    OwnerScopedPortfolioCorrelationEvidenceRepository,
    OwnerScopedPortfolioValuationEvidenceRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.recommendation_authorized_allocation_pipeline_service import (
    RecommendationAuthorizedAllocationPipelineService,
)


class _IdentityValuationValidator:
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return artifact


class _ActionRepository:
    def __init__(self, *, action_fingerprint: str, economic_contract_fingerprint: str) -> None:
        self._record = {
            "artifact": {
                "uncertaintyBoundActionCandidateFingerprint": action_fingerprint,
                "economicContractFingerprint": economic_contract_fingerprint,
            }
        }

    def get(self, *, candidate_fingerprint: str) -> dict[str, Any] | None:
        if candidate_fingerprint != self._record["artifact"][
            "uncertaintyBoundActionCandidateFingerprint"
        ]:
            return None
        return self._record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return record


class _EconomicContractAuthority:
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint

    def get(self, *, economic_contract_fingerprint: str) -> dict[str, Any] | None:
        if economic_contract_fingerprint != self._fingerprint:
            return None
        return {"economicContractFingerprint": self._fingerprint}


class _FailIfCalledVerifiedPipeline:
    def build(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("The verified pipeline must not run with foreign evidence.")


def _fingerprint(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _correlation_artifact() -> dict[str, Any]:
    core = {
        "artifactVersion": "athena-portfolio-correlation-evidence-v1",
        "leftInstrumentId": 101,
        "rightInstrumentId": 202,
        "sourceProvider": "owner-isolation-regression",
        "knowledgeCutoff": "2026-09-11T20:00:00+00:00",
        "sampleCount": 365,
        "correlation": 0.25,
        "firstReturnDate": "2025-09-11",
        "lastReturnDate": "2026-09-11",
        "latestRetrievedAt": "2026-09-11T19:59:00+00:00",
        "priceField": "adjusted_close",
        "alignmentPolicy": "intersection_by_observation_date",
        "returnPolicy": "simple_return",
    }
    return {
        **core,
        "portfolioCorrelationEvidenceFingerprint": _fingerprint(core),
        "status": "portfolio_correlation_evidence_verified_non_advisory",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _valuation_artifact() -> dict[str, Any]:
    fingerprint = hashlib.sha256(b"owner-isolation-valuation").hexdigest()
    return {
        "portfolioValuationEvidenceFingerprint": fingerprint,
        "asOf": "2026-09-11T20:00:00+00:00",
        "baseCurrency": "USD",
    }


def test_owner_scoped_evidence_does_not_grant_access_from_fingerprint_knowledge(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena-owner-isolation.sqlite3")

    valuation_repository = RecommendationPortfolioValuationEvidenceRepository(
        database=database,
        validator=_IdentityValuationValidator(),
    )
    valuation_a = OwnerScopedPortfolioValuationEvidenceRepository(
        owner_user_id=11,
        repository=valuation_repository,
    )
    valuation_b = OwnerScopedPortfolioValuationEvidenceRepository(
        owner_user_id=22,
        repository=valuation_repository,
    )
    valuation_record_a = valuation_a.seal(artifact=_valuation_artifact())
    valuation_fingerprint = valuation_record_a["valuation_fingerprint"]

    assert valuation_a.get(valuation_fingerprint=valuation_fingerprint) is not None
    assert valuation_b.get(valuation_fingerprint=valuation_fingerprint) is None

    correlation_repository = RecommendationPortfolioCorrelationEvidenceRepository(
        database=database
    )
    correlation_a = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=11,
        database=database,
        repository=correlation_repository,
    )
    correlation_b = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=22,
        database=database,
        repository=correlation_repository,
    )
    correlation_record_a = correlation_a.seal(artifact=_correlation_artifact())
    correlation_fingerprint = correlation_record_a["evidence_fingerprint"]

    assert correlation_a.get(evidence_fingerprint=correlation_fingerprint) is not None
    assert correlation_b.get(evidence_fingerprint=correlation_fingerprint) is None


def test_allocation_rejects_other_owners_real_persisted_correlation_fingerprint(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena-allocation-owner-isolation.sqlite3")
    backing_repository = RecommendationPortfolioCorrelationEvidenceRepository(database=database)
    owner_a_repository = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=11,
        database=database,
        repository=backing_repository,
    )
    owner_b_repository = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=22,
        database=database,
        repository=backing_repository,
    )

    owner_a_record = owner_a_repository.seal(artifact=_correlation_artifact())
    stolen_fingerprint = owner_a_record["evidence_fingerprint"]
    assert owner_b_repository.get(evidence_fingerprint=stolen_fingerprint) is None

    action_fingerprint = hashlib.sha256(b"sealed-action").hexdigest()
    contract_fingerprint = hashlib.sha256(b"sealed-economic-contract").hexdigest()
    service = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=owner_b_repository,
        action_repository=_ActionRepository(
            action_fingerprint=action_fingerprint,
            economic_contract_fingerprint=contract_fingerprint,
        ),
        economic_contract_authority=_EconomicContractAuthority(contract_fingerprint),
        verified_pipeline=_FailIfCalledVerifiedPipeline(),
    )

    with pytest.raises(
        ValueError,
        match="La evidencia de correlación requerida no está sellada",
    ):
        service.build(
            uncertainty_bound_action_candidate_fingerprint=action_fingerprint,
            allocation_policy_id="owner-isolation-regression",
            reference_capital=100_000.0,
            base_currency="USD",
            positions=[],
            correlation_evidence_fingerprints=[stolen_fingerprint],
            as_of=datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc),
        )


def test_same_evidence_requires_each_owner_to_seal_it_independently(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena-owner-linking.sqlite3")
    backing_repository = RecommendationPortfolioCorrelationEvidenceRepository(database=database)
    owner_a = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=11,
        database=database,
        repository=backing_repository,
    )
    owner_b = OwnerScopedPortfolioCorrelationEvidenceRepository(
        owner_user_id=22,
        database=database,
        repository=backing_repository,
    )

    artifact = _correlation_artifact()
    record_a = owner_a.seal(artifact=artifact)
    fingerprint = record_a["evidence_fingerprint"]
    assert owner_b.get(evidence_fingerprint=fingerprint) is None

    record_b = owner_b.seal(artifact=artifact)
    assert record_b["evidence_fingerprint"] == fingerprint
    assert owner_b.get(evidence_fingerprint=fingerprint) is not None

    with database.connect() as connection:
        evidence_count = connection.execute(
            "SELECT COUNT(*) AS count FROM athena_recommendation_portfolio_correlation_evidence"
        ).fetchone()["count"]
        ownership_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM athena_recommendation_portfolio_correlation_evidence_owners
            WHERE evidence_fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()["count"]

    assert evidence_count == 1
    assert ownership_count == 2

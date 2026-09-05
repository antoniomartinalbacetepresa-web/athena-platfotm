from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_authorized_allocation_pipeline_service import (
    RecommendationAuthorizedAllocationPipelineService,
)


AS_OF = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
FP_1 = "a" * 64
FP_2 = "b" * 64
RECORD_1 = "c" * 64
RECORD_2 = "d" * 64


def _artifact(*, fingerprint=FP_1, left=10, right=20):
    return {
        "status": "portfolio_correlation_evidence_verified_non_advisory",
        "artifactVersion": "athena-portfolio-correlation-evidence-v1",
        "leftInstrumentId": left,
        "rightInstrumentId": right,
        "sourceProvider": "YAHOO_CHART",
        "knowledgeCutoff": AS_OF.isoformat(),
        "sampleCount": 60,
        "correlation": 0.25,
        "firstReturnDate": "2026-06-01",
        "lastReturnDate": "2026-08-31",
        "latestRetrievedAt": "2026-09-01T11:00:00+00:00",
        "priceField": "adjusted_close",
        "alignmentPolicy": "utc_calendar_date_intersection",
        "returnPolicy": "simple_return_consecutive_observations_per_instrument",
        "portfolioCorrelationEvidenceFingerprint": fingerprint,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "allocationEligible": False,
        "automaticTrading": False,
    }


def _record(*, fingerprint=FP_1, record_fingerprint=RECORD_1, left=10, right=20):
    return {
        "evidence_fingerprint": fingerprint,
        "left_instrument_id": left,
        "right_instrument_id": right,
        "source_provider": "YAHOO_CHART",
        "knowledge_cutoff": AS_OF.isoformat(),
        "artifact": _artifact(fingerprint=fingerprint, left=left, right=right),
        "persisted_at": "2026-09-01T11:30:00+00:00",
        "record_fingerprint": record_fingerprint,
    }


class _CorrelationRepository:
    def __init__(self, records=None, *, substitute=False):
        self.records = {
            item["evidence_fingerprint"]: item for item in (records or [])
        }
        self.substitute = substitute

    def get(self, *, evidence_fingerprint):
        return self.records.get(evidence_fingerprint)

    def validate_record(self, record):
        return copy.deepcopy(record) if self.substitute else record


class _VerifiedPipeline:
    def __init__(self, *, unsafe=False):
        self.calls = []
        self.unsafe = unsafe

    def build(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return {
            "status": "verified_allocation_pipeline_non_advisory",
            "allocationCandidate": {"status": "allocation_candidate_non_advisory"},
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": self.unsafe,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {"automaticTrading": False},
        }


def _build(service, fingerprints):
    return service.build(
        uncertainty_bound_action_candidate_fingerprint="e" * 64,
        allocation_policy_id="allocation-001",
        economic_contract={"economicContractFingerprint": "f" * 64},
        reference_capital=10000.0,
        base_currency="EUR",
        positions=[],
        correlation_evidence_fingerprints=fingerprints,
        as_of=AS_OF,
    )


def test_authority_resolves_only_sealed_correlation_fingerprints():
    inner = _VerifiedPipeline()
    service = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([_record()]),
        verified_pipeline=inner,
    )

    result = _build(service, [FP_1])

    assert inner.calls[0]["correlation_evidence"] == [_artifact()]
    assert result["callerSuppliedCorrelationArtifactsAccepted"] is False
    assert result["correlationAuthorityBoundToAllocation"] is True
    assert result["correlationAuthority"] == [
        {
            "evidenceFingerprint": FP_1,
            "recordFingerprint": RECORD_1,
            "persistedAt": "2026-09-01T11:30:00+00:00",
            "leftInstrumentId": 10,
            "rightInstrumentId": 20,
        }
    ]
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["callerSuppliedCorrelationJsonAccepted"] is False


def test_unknown_or_substituted_correlation_authority_fails_closed():
    missing = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([]),
        verified_pipeline=_VerifiedPipeline(),
    )
    with pytest.raises(ValueError, match="no está sellada"):
        _build(missing, [FP_1])

    substituted = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([_record()], substitute=True),
        verified_pipeline=_VerifiedPipeline(),
    )
    with pytest.raises(ValueError, match="sustituyó un registro"):
        _build(substituted, [FP_1])


def test_tampered_fingerprint_binding_fails_closed():
    record = _record()
    record["artifact"]["portfolioCorrelationEvidenceFingerprint"] = "9" * 64
    service = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([record]),
        verified_pipeline=_VerifiedPipeline(),
    )
    with pytest.raises(ValueError, match="no corresponde al registro"):
        _build(service, [FP_1])


def test_duplicate_fingerprint_or_pair_fails_closed():
    service = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([_record()]),
        verified_pipeline=_VerifiedPipeline(),
    )
    with pytest.raises(ValueError, match="fingerprint de correlación duplicado"):
        _build(service, [FP_1, FP_1])

    second = _record(
        fingerprint=FP_2,
        record_fingerprint=RECORD_2,
        left=20,
        right=10,
    )
    pair_duplicate = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([_record(), second]),
        verified_pipeline=_VerifiedPipeline(),
    )
    with pytest.raises(ValueError, match="mismo par"):
        _build(pair_duplicate, [FP_1, FP_2])


def test_inner_pipeline_cannot_escape_production_gate():
    service = RecommendationAuthorizedAllocationPipelineService(
        correlation_repository=_CorrelationRepository([]),
        verified_pipeline=_VerifiedPipeline(unsafe=True),
    )
    with pytest.raises(ValueError, match="productionEligible"):
        _build(service, [])

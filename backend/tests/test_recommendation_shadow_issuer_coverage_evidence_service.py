import hashlib
import json

import pytest

from app.services.recommendation_shadow_issuer_coverage_evidence_service import (
    RecommendationShadowIssuerCoverageEvidenceService,
)


class FakeIssuerIdentityRepository:
    def __init__(self, identities: dict[int, dict[str, object] | None]) -> None:
        self.identities = identities

    def get_issuer_for_instrument(self, instrument_id: int) -> dict[str, object] | None:
        return self.identities.get(instrument_id)


def _fingerprint(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _dataset(rows: list[dict[str, object]]) -> dict[str, object]:
    core: dict[str, object] = {
        "datasetVersion": "shadow-action-calibration-v2",
        "asOf": "2026-09-07T16:00:00+00:00",
        "symbol": None,
        "requestedHorizons": [7, 30],
        "rowCount": len(rows),
        "rows": rows,
    }
    return {
        "status": "shadow_action_calibration_dataset_available" if rows else "shadow_action_calibration_dataset_pending",
        **core,
        "datasetFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
    }


def _row(instrument_id: int, candidate_id: int, horizon: int) -> dict[str, object]:
    return {
        "instrumentId": instrument_id,
        "candidateId": candidate_id,
        "candidateAsOf": f"2026-01-{candidate_id:02d}T16:00:00+00:00",
        "horizonDays": horizon,
    }


def _resolved(issuer_id: int) -> dict[str, object]:
    return {
        "issuer_id": issuer_id,
        "canonical_name": f"Issuer {issuer_id}",
        "domicile_country": "United States",
        "region_key": "america",
        "evidence_source": "sec_company_tickers_exchange",
        "resolution_method": "exact_ticker_unique_cik",
        "confidence": 0.95,
    }


def test_build_seals_resolved_and_unresolved_issuer_coverage_without_collapsing_securities() -> None:
    dataset = _dataset(
        [
            _row(10, 1, 7),
            _row(11, 2, 7),
            _row(12, 3, 7),
            _row(10, 4, 30),
        ]
    )
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository(
            {
                10: _resolved(100),
                11: _resolved(100),  # distinct security/listing, same issuer
                12: None,
            }
        )
    )

    artifact = service.build(dataset)

    assert artifact["resolvedIssuerRowCount"] == 3
    assert artifact["unresolvedIssuerRowCount"] == 1
    assert artifact["distinctResolvedIssuerCount"] == 1
    assert artifact["maximumRowsPerResolvedIssuer"] == 3
    assert artifact["horizons"]["7"] == {
        "horizonDays": 7,
        "rowCount": 3,
        "resolvedIssuerRowCount": 2,
        "unresolvedIssuerRowCount": 1,
        "distinctResolvedIssuerCount": 1,
        "maximumRowsPerResolvedIssuer": 2,
    }
    assert len(artifact["instrumentIdentityEvidence"]) == 3
    assert artifact["policy"]["securityDeduplication"] == "not_performed_by_issuer"
    assert artifact["policy"]["statisticalIndependence"] == "not_claimed"
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["recommendationCandidateReady"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["issuerCoverageGatePassed"] is False
    assert artifact["policy"]["automaticProductionPromotion"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert service.validate_artifact(artifact) is artifact


def test_unresolved_identity_is_counted_and_never_inferred_from_symbol() -> None:
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository({})
    )

    artifact = service.build(_dataset([_row(55, 1, 7)]))

    evidence = artifact["instrumentIdentityEvidence"][0]
    assert evidence["status"] == "issuer_identity_unresolved"
    assert evidence["issuerId"] is None
    assert evidence["evidenceSource"] is None
    assert artifact["resolvedIssuerRowCount"] == 0
    assert artifact["unresolvedIssuerRowCount"] == 1


def test_tampered_dataset_fingerprint_fails_closed() -> None:
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository({10: _resolved(100)})
    )
    dataset = _dataset([_row(10, 1, 7)])
    dataset["rows"][0]["instrumentId"] = 11

    with pytest.raises(ValueError, match="modificado"):
        service.build(dataset)


def test_nonfinite_identity_confidence_fails_closed() -> None:
    identity = _resolved(100)
    identity["confidence"] = float("nan")
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository({10: identity})
    )

    with pytest.raises(ValueError, match="confidence"):
        service.build(_dataset([_row(10, 1, 7)]))


def test_tampered_coverage_artifact_fails_closed() -> None:
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository({10: _resolved(100)})
    )
    artifact = service.build(_dataset([_row(10, 1, 7)]))
    artifact["distinctResolvedIssuerCount"] = 999

    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(artifact)


def test_artifact_cannot_claim_production_weighting_or_independence() -> None:
    service = RecommendationShadowIssuerCoverageEvidenceService(
        identity_repository=FakeIssuerIdentityRepository({10: _resolved(100)})
    )
    artifact = service.build(_dataset([_row(10, 1, 7)]))

    for field in ("productionEligible", "recommendationCandidateReady", "isWeightingReady", "issuerCoverageGatePassed"):
        mutated = json.loads(json.dumps(artifact))
        mutated[field] = True
        with pytest.raises(ValueError):
            service.validate_artifact(mutated)

    mutated = json.loads(json.dumps(artifact))
    mutated["policy"]["statisticalIndependence"] = "claimed"
    with pytest.raises(ValueError, match="independencia"):
        service.validate_artifact(mutated)

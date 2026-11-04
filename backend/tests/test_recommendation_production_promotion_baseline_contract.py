from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_production_promotion_evidence_service import (
    RecommendationProductionPromotionEvidenceService,
)


def _protocol_core() -> dict:
    return {
        "artifactVersion": "athena-production-promotion-protocol-v1",
        "protocolId": "baseline-contract",
        "registeredAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "researchGateFingerprint": "gate-abc",
        "requiredHorizons": [7],
        "criteriaByHorizon": {
            "7": {
                "minimumConfirmationRowCount": 20,
                "minimumNonOverlappingConfirmationWindowCount": 5,
                "minimumResolvedIssuerCoverageRatio": 0.90,
                "maximumResolvedIssuerConcentrationRatio": 0.25,
                "minimumSignAccuracy": 0.0,
                "minimumRelativeMseImprovement": 0.01,
                "requireBeatZeroExcessMseBaseline": True,
            }
        },
    }


def test_direct_protocol_path_rejects_zero_or_negative_mse_improvement() -> None:
    service = RecommendationProductionPromotionEvidenceService()

    zero = deepcopy(_protocol_core())
    zero["criteriaByHorizon"]["7"]["minimumRelativeMseImprovement"] = 0.0
    with pytest.raises(ValueError, match="estrictamente positivo"):
        service.fingerprint_protocol(zero)

    negative = deepcopy(_protocol_core())
    negative["criteriaByHorizon"]["7"]["minimumRelativeMseImprovement"] = -0.01
    with pytest.raises(ValueError, match="estrictamente positivo"):
        service.fingerprint_protocol(negative)


def test_direct_protocol_path_cannot_make_zero_baseline_optional() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = deepcopy(_protocol_core())
    protocol["criteriaByHorizon"]["7"]["requireBeatZeroExcessMseBaseline"] = False

    with pytest.raises(ValueError, match="debe ser true"):
        service.fingerprint_protocol(protocol)


def test_valid_structural_baseline_contract_remains_fingerprinted() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol_core()

    fingerprint = service.fingerprint_protocol(protocol)

    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)

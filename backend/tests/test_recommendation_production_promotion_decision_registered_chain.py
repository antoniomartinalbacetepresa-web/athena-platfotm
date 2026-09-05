from __future__ import annotations

import hashlib
import json

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_promotion_decision_repository import (
    RecommendationProductionPromotionDecisionRepository,
)
from app.repositories.recommendation_production_promotion_protocol_repository import (
    RecommendationProductionPromotionProtocolRepository,
)
from app.services.recommendation_production_promotion_decision_service import (
    RecommendationProductionPromotionDecisionService,
)
from app.services.recommendation_production_promotion_evidence_service import (
    RecommendationProductionPromotionEvidenceService,
)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _protocol_draft() -> dict:
    return {
        "artifactVersion": "athena-production-promotion-protocol-v1",
        "protocolId": "registered-chain-v1",
        "researchGateFingerprint": "a" * 64,
        "requiredHorizons": [7, 30],
        "criteriaByHorizon": {
            "7": {
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
            "30": {
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
        },
    }


def _confirmation() -> dict:
    core = {
        "artifactVersion": "shadow-post-selection-multi-horizon-v1",
        "researchGateFingerprint": "a" * 64,
        "researchCutoff": "2099-01-01T00:00:00+00:00",
        "asOf": "2099-12-31T00:00:00+00:00",
        "requestedHorizons": [7, 30],
        "confirmedHorizonCount": 2,
        "passingHorizonCount": 2,
        "confirmationPassRatio": 1.0,
        "postSelectionProtocolEvidenceReady": True,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "confirmed": True,
                "modelFingerprint": "7" * 64,
                "selectionFingerprint": "8" * 64,
                "confirmationStart": "2099-01-02T00:00:00+00:00",
                "confirmationRowCount": 30,
                "metrics": {"signAccuracy": 0.60, "mse": 0.02},
                "relativeMseImprovement": 0.10,
                "beatsZeroBaselineOnMse": True,
            },
            "30": {
                "horizonDays": 30,
                "confirmed": True,
                "modelFingerprint": "3" * 64,
                "selectionFingerprint": "4" * 64,
                "confirmationStart": "2099-01-02T00:00:00+00:00",
                "confirmationRowCount": 30,
                "metrics": {"signAccuracy": 0.59, "mse": 0.03},
                "relativeMseImprovement": 0.09,
                "beatsZeroBaselineOnMse": True,
            },
        },
        "thresholds": {"researchOnly": True},
    }
    return {
        **core,
        "confirmationEvidenceFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_registered_protocol_to_oos_evidence_to_immutable_decision_chain(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    protocol_repository = RecommendationProductionPromotionProtocolRepository(database)
    protocol_record = protocol_repository.register(protocol_draft=_protocol_draft())
    evidence_service = RecommendationProductionPromotionEvidenceService(protocol_repository)

    evidence = evidence_service.evaluate_registered(
        confirmation_artifact=_confirmation(),
        protocol_id=protocol_record["protocol_id"],
    )
    assert evidence["productionPromotionEvidenceReady"] is True

    decision_repository = RecommendationProductionPromotionDecisionRepository(database)
    decision_service = RecommendationProductionPromotionDecisionService(decision_repository)
    decision = decision_service.decide(
        decision_id="decision-chain-v1",
        promotion_evidence=evidence,
    )

    assert decision["calibrationEvidenceReady"] is True
    assert decision["researchGateFingerprint"] == "a" * 64
    assert decision["confirmationEvidenceFingerprint"] == _confirmation()[
        "confirmationEvidenceFingerprint"
    ]
    assert decision["modelFingerprintsByHorizon"] == {
        "7": "7" * 64,
        "30": "3" * 64,
    }
    assert decision["selectionFingerprintsByHorizon"] == {
        "7": "8" * 64,
        "30": "4" * 64,
    }
    assert decision["advisoryStatus"] == "no_advice"
    assert decision["recommendationCandidateReady"] is False
    assert decision["productionEligible"] is False
    assert decision["automaticProductionPromotion"] is False
    assert decision["automaticTrading"] is False

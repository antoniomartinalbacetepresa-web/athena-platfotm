from __future__ import annotations

import hashlib
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_promotion_protocol_repository import (
    RecommendationProductionPromotionProtocolRepository,
)
from app.services.recommendation_production_promotion_evidence_service import (
    RecommendationProductionPromotionEvidenceService,
)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _confirmation(*, research_cutoff: str) -> dict:
    core = {
        "artifactVersion": "shadow-post-selection-multi-horizon-v1",
        "researchGateFingerprint": "a" * 64,
        "researchCutoff": research_cutoff,
        "asOf": "2099-12-31T00:00:00+00:00",
        "requestedHorizons": [7],
        "confirmedHorizonCount": 1,
        "passingHorizonCount": 1,
        "confirmationPassRatio": 1.0,
        "postSelectionProtocolEvidenceReady": True,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "confirmed": True,
                "modelFingerprint": "model-7",
                "selectionFingerprint": "selection-7",
                "confirmationStart": "2099-01-02T00:00:00+00:00",
                "confirmationRowCount": 30,
                "metrics": {"signAccuracy": 0.60, "mse": 0.02},
                "relativeMseImprovement": 0.10,
                "beatsZeroBaselineOnMse": True,
            }
        },
        "thresholds": {"researchOnly": True},
    }
    return {
        **core,
        "confirmationEvidenceFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _draft() -> dict:
    return {
        "artifactVersion": "athena-production-promotion-protocol-v1",
        "protocolId": "registered-protocol-001",
        "researchGateFingerprint": "a" * 64,
        "requiredHorizons": [7],
        "criteriaByHorizon": {
            "7": {
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            }
        },
    }


def test_registered_path_proves_persistence_without_enabling_advice(tmp_path):
    repository = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    record = repository.register(protocol_draft=_draft())
    service = RecommendationProductionPromotionEvidenceService(repository)

    result = service.evaluate_registered(
        confirmation_artifact=_confirmation(
            research_cutoff="2099-01-01T00:00:00+00:00"
        ),
        protocol_id=record["protocol_id"],
    )

    assert result["productionPromotionEvidenceReady"] is True
    assert result["protocolPersistence"]["registered"] is True
    assert result["protocolPersistence"]["protocolFingerprint"] == record[
        "protocol_fingerprint"
    ]
    assert result["policy"]["registeredProtocolRequiredForProductionPath"] is True
    assert result["policy"]["callerSuppliedRegistrationTimeAccepted"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["automaticProductionPromotion"] is False
    assert result["automaticTrading"] is False


def test_registered_path_rejects_unknown_protocol(tmp_path):
    repository = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    service = RecommendationProductionPromotionEvidenceService(repository)

    with pytest.raises(ValueError, match="no está registrado"):
        service.evaluate_registered(
            confirmation_artifact=_confirmation(
                research_cutoff="2099-01-01T00:00:00+00:00"
            ),
            protocol_id="missing-protocol",
        )


def test_protocol_registered_after_cutoff_cannot_validate_old_evidence(tmp_path):
    repository = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    record = repository.register(protocol_draft=_draft())
    service = RecommendationProductionPromotionEvidenceService(repository)

    with pytest.raises(ValueError, match="researchCutoff"):
        service.evaluate_registered(
            confirmation_artifact=_confirmation(
                research_cutoff="2000-01-01T00:00:00+00:00"
            ),
            protocol_id=record["protocol_id"],
        )

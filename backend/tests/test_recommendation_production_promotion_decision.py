from __future__ import annotations

import copy
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_promotion_decision_repository import (
    RecommendationProductionPromotionDecisionRepository,
)
from app.services.recommendation_production_promotion_decision_service import (
    RecommendationProductionPromotionDecisionService,
)


def _evidence() -> dict:
    horizons = (7, 30, 90, 180, 365)
    return {
        "status": "production_promotion_evidence_ready",
        "protocolId": "prod-v1",
        "protocolFingerprint": "b" * 64,
        "researchGateFingerprint": "a" * 64,
        "researchCutoff": "2026-01-01T00:00:00+00:00",
        "confirmationEvidenceFingerprint": "c" * 64,
        "requiredHorizons": list(horizons),
        "horizons": {
            str(h): {
                "horizonDays": h,
                "passesPrecommittedCriteria": True,
                "blockers": [],
                "modelFingerprint": f"{h % 10:x}" * 64,
                "selectionFingerprint": f"{(h + 1) % 10:x}" * 64,
            }
            for h in horizons
        },
        "productionPromotionEvidenceReady": True,
        "advisoryStatus": "no_advice",
        "recommendationCandidateReady": False,
        "productionEligible": False,
        "automaticProductionPromotion": False,
        "automaticTrading": False,
        "protocolPersistence": {
            "registered": True,
            "protocolFingerprint": "b" * 64,
        },
    }


def _service(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationProductionPromotionDecisionRepository(database)
    return RecommendationProductionPromotionDecisionService(repository), repository, database


def test_ready_registered_oos_evidence_becomes_calibration_evidence_only(tmp_path):
    service, repository, _ = _service(tmp_path)
    result = service.decide(decision_id="decision-v1", promotion_evidence=_evidence())

    assert result["status"] == "promotion_evidence_accepted_for_calibration"
    assert result["calibrationEvidenceReady"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["automaticProductionPromotion"] is False
    assert result["automaticTrading"] is False
    assert set(result["modelFingerprintsByHorizon"]) == {"7", "30", "90", "180", "365"}
    persisted = repository.get(decision_id="decision-v1")
    assert persisted is not None
    assert persisted["decision"]["decisionFingerprint"] == persisted["decision_fingerprint"]


def test_caller_cannot_backdate_or_supply_decision_fingerprint(tmp_path):
    _, repository, _ = _service(tmp_path)
    draft = {
        "artifactVersion": repository.ARTIFACT_VERSION,
        "decisionId": "forged",
        "researchGateFingerprint": "a" * 64,
        "protocolId": "prod-v1",
        "protocolFingerprint": "b" * 64,
        "confirmationEvidenceFingerprint": "c" * 64,
        "evidenceAssessmentFingerprint": "d" * 64,
        "requiredHorizons": [7],
        "modelFingerprintsByHorizon": {"7": "e" * 64},
        "selectionFingerprintsByHorizon": {"7": "f" * 64},
        "decidedAt": "2000-01-01T00:00:00+00:00",
    }
    with pytest.raises(ValueError, match="los genera el registro"):
        repository.register(decision_draft=draft)
    draft.pop("decidedAt")
    draft["decisionFingerprint"] = "1" * 64
    with pytest.raises(ValueError, match="los genera el registro"):
        repository.register(decision_draft=draft)


def test_decision_requires_exact_registered_protocol_and_all_horizons_pass(tmp_path):
    service, _, _ = _service(tmp_path)
    unregistered = _evidence()
    unregistered["protocolPersistence"]["registered"] = False
    with pytest.raises(ValueError, match="protocolo persistido"):
        service.decide(decision_id="unregistered", promotion_evidence=unregistered)

    failed = _evidence()
    failed["horizons"]["90"]["passesPrecommittedCriteria"] = False
    failed["horizons"]["90"]["blockers"] = ["failed"]
    with pytest.raises(ValueError, match="Todos los horizontes"):
        service.decide(decision_id="failed", promotion_evidence=failed)


def test_model_or_selection_identity_cannot_be_missing_or_malformed(tmp_path):
    service, _, _ = _service(tmp_path)
    missing_model = _evidence()
    missing_model["horizons"]["30"]["modelFingerprint"] = None
    with pytest.raises(ValueError, match="modelFingerprint"):
        service.decide(decision_id="missing-model", promotion_evidence=missing_model)

    malformed_selection = _evidence()
    malformed_selection["horizons"]["365"]["selectionFingerprint"] = "not-a-hash"
    with pytest.raises(ValueError, match="selectionFingerprint"):
        service.decide(decision_id="bad-selection", promotion_evidence=malformed_selection)


def test_same_sealed_evidence_cannot_be_redeclared_under_another_decision(tmp_path):
    service, _, _ = _service(tmp_path)
    service.decide(decision_id="first", promotion_evidence=_evidence())
    with pytest.raises(Exception):
        service.decide(decision_id="second", promotion_evidence=_evidence())


def test_tampered_persisted_decision_fails_closed(tmp_path):
    service, repository, database = _service(tmp_path)
    service.decide(decision_id="decision-v1", promotion_evidence=_evidence())
    record = repository.get(decision_id="decision-v1")
    assert record is not None
    changed = copy.deepcopy(record["decision"])
    changed["modelFingerprintsByHorizon"]["7"] = "9" * 64
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_production_promotion_decisions
            SET decision_json = ? WHERE decision_id = ?
            """,
            (json.dumps(changed, sort_keys=True, separators=(",", ":")), "decision-v1"),
        )
    with pytest.raises(ValueError, match="modificada"):
        repository.get(decision_id="decision-v1")

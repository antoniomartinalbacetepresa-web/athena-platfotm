from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput,
    RecommendationDevilsAdvocateService,
)


AS_OF = datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc)
SNAPSHOT_HASH = "a" * 64


def _evidence(**overrides):
    values = {
        "evidence_id": "ev-1",
        "kind": "valuation_risk",
        "claim": "El múltiplo exigido por la tesis puede ser demasiado alto frente a la evidencia PIT disponible.",
        "strength": "material",
        "available_at": AS_OF - timedelta(minutes=5),
        "source": "athena-reverse-valuation",
        "source_ref": "rv-1",
    }
    values.update(overrides)
    return DevilsAdvocateEvidenceInput(**values)


def _review(**overrides):
    values = {
        "journal_id": "journal-aapl",
        "revision_id": "rev-1",
        "snapshot_hash": SNAPSHOT_HASH,
        "symbol": "aapl",
        "as_of": AS_OF,
        "evidence": (_evidence(),),
    }
    values.update(overrides)
    return RecommendationDevilsAdvocateService().review(**values)


def test_review_preserves_pit_provenance_and_no_advice_contract():
    payload = _review().to_api_dict()

    assert payload["symbol"] == "AAPL"
    assert payload["evidenceCount"] == 1
    assert payload["strengthCounts"]["material"] == 1
    assert payload["coveredKinds"] == ["valuation_risk"]
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["scoring"] == "no_numeric_score_or_probability_without_independent_calibration"
    assert payload["evidence"][0]["sourceRef"] == "rv-1"


def test_review_rejects_lookahead():
    with pytest.raises(ValueError, match="look-ahead"):
        _review(evidence=(_evidence(available_at=AS_OF + timedelta(seconds=1)),))


def test_review_rejects_duplicate_evidence_identity():
    with pytest.raises(ValueError, match="evidence_id"):
        _review(evidence=(_evidence(), _evidence(kind="data_quality")))


@pytest.mark.parametrize("field", ["source", "source_ref", "claim"])
def test_review_requires_provenance_and_explicit_claim(field: str):
    with pytest.raises(ValueError, match="obligatorio"):
        _review(evidence=(_evidence(**{field: " "}),))


@pytest.mark.parametrize("strength", ["severe", "0.9", "buy", "sell"])
def test_review_rejects_uncalibrated_or_action_strengths(strength: str):
    with pytest.raises(ValueError, match="strength"):
        _review(evidence=(_evidence(strength=strength),))


def test_review_rejects_unknown_kind_and_naive_time():
    with pytest.raises(ValueError, match="kind"):
        _review(evidence=(_evidence(kind="technical_pattern_opinion"),))
    with pytest.raises(ValueError, match="zona horaria"):
        _review(as_of=AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="zona horaria"):
        _review(evidence=(_evidence(available_at=AS_OF.replace(tzinfo=None)),))


def test_review_rejects_invalid_snapshot_hash():
    with pytest.raises(ValueError, match="SHA-256"):
        _review(snapshot_hash="not-a-hash")


def test_api_exposes_research_only_contract():
    client = TestClient(app)
    response = client.post(
        "/api/v1/recommendations/professional-research/devils-advocate",
        json={
            "journalId": "journal-aapl",
            "revisionId": "rev-1",
            "snapshotHash": SNAPSHOT_HASH,
            "symbol": "AAPL",
            "asOf": AS_OF.isoformat(),
            "evidence": [
                {
                    "evidenceId": "ev-1",
                    "kind": "scenario_downside",
                    "claim": "El escenario bajista conserva una pérdida material bajo supuestos PIT explícitos.",
                    "strength": "critical",
                    "availableAt": (AS_OF - timedelta(minutes=1)).isoformat(),
                    "source": "athena-scenario-asymmetry",
                    "sourceRef": "scenario-1",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["fabrication"].startswith("only_explicit_caller_supplied")
    assert payload["policy"]["automaticTrading"] is False


def test_api_rejects_naive_temporal_evidence():
    client = TestClient(app)
    response = client.post(
        "/api/v1/recommendations/professional-research/devils-advocate",
        json={
            "journalId": "journal-aapl",
            "revisionId": "rev-1",
            "snapshotHash": SNAPSHOT_HASH,
            "symbol": "AAPL",
            "asOf": AS_OF.isoformat(),
            "evidence": [
                {
                    "evidenceId": "ev-1",
                    "kind": "data_quality",
                    "claim": "Una fuente clave presenta cobertura incompleta.",
                    "strength": "weak",
                    "availableAt": "2026-09-08T01:20:00",
                    "source": "athena-quality",
                    "sourceRef": "quality-1",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

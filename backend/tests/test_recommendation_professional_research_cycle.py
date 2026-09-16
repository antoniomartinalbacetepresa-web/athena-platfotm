from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput,
    RecommendationDevilsAdvocateService,
)
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)
from app.services.recommendation_professional_research_cycle_service import (
    RecommendationProfessionalResearchCycleService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
RECORDED_AT = AS_OF - timedelta(hours=1)


def _artifacts(*, radar_source: str = "athena-test", journal_source: str = "athena-test", fx: bool = False):
    radar_evidence = [
        AthenaRadarEvidenceInput(
            evidence_id="radar-1",
            category="thesis_invalidation",
            urgency="material",
            summary="A material research question requires review.",
            available_at=RECORDED_AT,
            source=radar_source,
            source_ref="urn:radar:1",
        )
    ]
    if fx:
        radar_evidence.append(
            AthenaRadarEvidenceInput(
                evidence_id="radar-fx",
                category="fx",
                urgency="routine",
                summary="Explicit USD FX exposure evidence.",
                available_at=RECORDED_AT,
                source="athena-fx",
                source_ref="urn:fx:1",
            )
        )
    radar = RecommendationAthenaRadarService().build(
        as_of=AS_OF,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                evidence=tuple(radar_evidence),
            ),
        ),
    )
    journal = RecommendationInvestmentJournalService().freeze_snapshot(
        journal_id="journal-aapl",
        revision_id="revision-1",
        symbol="AAPL",
        recorded_at=RECORDED_AT,
        as_of=AS_OF,
        thesis="Frozen thesis before outcome evidence.",
        references=(
            InvestmentJournalReferenceInput(
                reference_id="journal-ref-1",
                kind="assumption",
                available_at=RECORDED_AT - timedelta(minutes=1),
                source=journal_source,
                source_ref="urn:journal:1",
            ),
        ),
    )
    devil = RecommendationDevilsAdvocateService().review(
        journal_id=journal.journal_id,
        revision_id=journal.revision_id,
        snapshot_hash=journal.snapshot_hash,
        symbol="AAPL",
        as_of=AS_OF,
        evidence=(
            DevilsAdvocateEvidenceInput(
                evidence_id="devil-1",
                kind="alternative_explanation",
                claim="The observed evidence may have a non-thesis explanation.",
                strength="material",
                available_at=RECORDED_AT,
                source="athena-test",
                source_ref="urn:devil:1",
            ),
        ),
    )
    return radar, journal, devil


def _payload(*, radar_available_at: datetime = RECORDED_AT) -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "radarEvidence": [
            {
                "evidenceId": "radar-1",
                "category": "thesis_invalidation",
                "urgency": "material",
                "summary": "Material research question.",
                "availableAt": radar_available_at.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:radar:1",
            }
        ],
        "journalId": "journal-aapl",
        "revisionId": "revision-1",
        "recordedAt": RECORDED_AT.isoformat(),
        "thesis": "Frozen thesis before outcome evidence.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-1",
                "kind": "assumption",
                "availableAt": (RECORDED_AT - timedelta(minutes=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:journal:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-1",
                "kind": "alternative_explanation",
                "claim": "Alternative explanation requires human review.",
                "strength": "material",
                "availableAt": RECORDED_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:1",
            }
        ],
    }


def test_cycle_binds_exact_identity_snapshot_and_pit_cutoff() -> None:
    radar, journal, devil = _artifacts()
    result = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl",
        radar=radar,
        journal=journal,
        devils_advocate=devil,
    ).to_api_dict()

    assert result["status"] == "professional_research_cycle_ready_for_human_review"
    assert result["symbol"] == "AAPL"
    assert result["journal"]["snapshotHash"] == journal.snapshot_hash
    assert result["journal"]["snapshotBindingVerified"] is True
    assert result["researchUrgency"] == "material"
    assert result["researchUrgencyInterpretation"] == "attention_priority_not_investment_preference"
    assert result["fxEvidenceStatus"] == "unknown_not_neutral"
    assert result["humanReviewRequired"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["policy"]["automaticTrading"] is False
    assert result["policy"]["automaticProductionPromotion"] is False
    assert result["integrity"]["algorithm"] == "sha256"
    assert result["integrity"]["journalSnapshotHash"] == journal.snapshot_hash
    assert len(result["integrity"]["radarHash"]) == 64
    assert len(result["integrity"]["devilsAdvocateHash"]) == 64
    assert len(result["integrity"]["cycleHash"]) == 64
    assert result["policy"]["tamperEvidence"] == "cycle_hash_binds_canonical_radar_journal_and_devils_advocate_artifacts"
    assert "score" not in result
    assert "expectedReturn" not in result
    assert "probability" not in result
    assert "targetWeight" not in result


def test_cycle_integrity_hash_is_deterministic_and_binds_provenance() -> None:
    radar, journal, devil = _artifacts()
    service = RecommendationProfessionalResearchCycleService()
    first = service.bind(
        instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
    ).to_api_dict()
    second = service.bind(
        instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
    ).to_api_dict()
    changed_radar, changed_journal, changed_devil = _artifacts(radar_source="athena-test-mutated")
    changed = service.bind(
        instrument_id="instrument-aapl",
        radar=changed_radar,
        journal=changed_journal,
        devils_advocate=changed_devil,
    ).to_api_dict()

    assert first["integrity"] == second["integrity"]
    assert first["integrity"]["radarHash"] != changed["integrity"]["radarHash"]
    assert first["integrity"]["cycleHash"] != changed["integrity"]["cycleHash"]
    assert first["integrity"]["journalSnapshotHash"] == changed["integrity"]["journalSnapshotHash"]


def test_cycle_marks_fx_only_when_explicit_evidence_exists() -> None:
    radar, journal, devil = _artifacts(fx=True)
    result = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
    ).to_api_dict()
    assert result["fxEvidenceStatus"] == "explicit"


def test_cycle_rejects_wrong_journal_snapshot_binding() -> None:
    radar, journal, _ = _artifacts()
    devil = RecommendationDevilsAdvocateService().review(
        journal_id=journal.journal_id,
        revision_id=journal.revision_id,
        snapshot_hash="0" * 64,
        symbol="AAPL",
        as_of=AS_OF,
        evidence=(
            DevilsAdvocateEvidenceInput(
                evidence_id="devil-x",
                kind="data_quality",
                claim="Contradictory data-quality evidence.",
                strength="weak",
                available_at=RECORDED_AT,
                source="athena-test",
                source_ref="urn:devil:x",
            ),
        ),
    )
    with pytest.raises(ValueError, match="snapshot_hash exacto"):
        RecommendationProfessionalResearchCycleService().bind(
            instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
        )


def test_cycle_rejects_fmp_across_modules_even_when_underlying_module_accepts_it() -> None:
    radar, journal, devil = _artifacts(journal_source="Financial Modeling Prep")
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        RecommendationProfessionalResearchCycleService().bind(
            instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
        )


def test_cycle_api_persists_lineage_and_remains_research_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = RecommendationInvestmentJournalRepository(AthenaDatabase(tmp_path / "cycle.db"))
    monkeypatch.setattr(cycle_api, "journal_repository", repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["journalPersistence"]["appendOnly"] is True
    assert data["journalPersistence"]["lineageVerified"] is True
    assert data["journalPersistence"]["headSnapshotHash"] == data["journal"]["snapshotHash"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["integrity"]["journalSnapshotHash"] == data["journal"]["snapshotHash"]
    assert len(data["integrity"]["cycleHash"]) == 64
    assert repository.verify_lineage(journal_id="journal-aapl")["revisionCount"] == 1


def test_cycle_api_rejects_look_ahead_before_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = RecommendationInvestmentJournalRepository(AthenaDatabase(tmp_path / "cycle-lookahead.db"))
    monkeypatch.setattr(cycle_api, "journal_repository", repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(radar_available_at=AS_OF + timedelta(seconds=1)),
    )

    assert response.status_code == 400
    with pytest.raises(ValueError, match="No existe un journal"):
        repository.verify_lineage(journal_id="journal-aapl")


def test_cycle_api_contract_fails_closed_on_production_or_weighting() -> None:
    radar, journal, devil = _artifacts()
    payload = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl", radar=radar, journal=journal, devils_advocate=devil
    ).to_api_dict()

    payload["productionEligible"] = True
    with pytest.raises(HTTPException):
        cycle_api._assert_cycle_contract(payload)

    payload["productionEligible"] = False
    payload["isWeightingReady"] = True
    with pytest.raises(HTTPException):
        cycle_api._assert_cycle_contract(payload)


def test_cycle_route_is_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations/professional-research/research-cycle" in paths

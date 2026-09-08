from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
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


def _artifacts(*, radar_source: str = "athena-test"):
    radar = RecommendationAthenaRadarService().build(
        as_of=AS_OF,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                evidence=(
                    AthenaRadarEvidenceInput(
                        evidence_id="radar-1",
                        category="thesis_invalidation",
                        urgency="material",
                        summary="Material question requiring research.",
                        available_at=RECORDED_AT,
                        source=radar_source,
                        source_ref="urn:radar:1",
                    ),
                ),
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
                source="athena-test",
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
                claim="Alternative explanation requires review.",
                strength="material",
                available_at=RECORDED_AT,
                source="athena-test",
                source_ref="urn:devil:1",
            ),
        ),
    )
    cycle = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl",
        radar=radar,
        journal=journal,
        devils_advocate=devil,
    )
    return radar, journal, devil, cycle


def _append(repository: RecommendationProfessionalResearchCycleRepository, *, radar_source: str = "athena-test"):
    radar, journal, devil, cycle = _artifacts(radar_source=radar_source)
    return repository.append(
        cycle_payload=cycle.to_api_dict(),
        radar_payload=radar.to_api_dict(),
        journal_payload=journal.to_api_dict(),
        devils_advocate_payload=devil.to_api_dict(),
    )


def _request_payload() -> dict[str, object]:
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
                "availableAt": RECORDED_AT.isoformat(),
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


def test_cycle_repository_persists_and_reverifies_complete_package(tmp_path: Path) -> None:
    repository = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "cycle.db"))
    record = _append(repository)

    loaded = repository.get_by_hash(cycle_hash=record["cycle_hash"])

    assert loaded["cycle_hash"] == record["cycle_hash"]
    assert loaded["package"]["cycle"]["advisoryStatus"] == "no_advice"
    assert loaded["package"]["cycle"]["productionEligible"] is False
    assert loaded["package"]["cycle"]["isWeightingReady"] is False
    assert loaded["package"]["radar"]["candidates"][0]["evidence"][0]["source"] == "athena-test"
    assert loaded["package"]["journal"]["snapshotHash"] == loaded["snapshot_hash"]
    assert loaded["package"]["devilsAdvocate"]["snapshotHash"] == loaded["snapshot_hash"]


def test_cycle_repository_is_idempotent_but_rejects_rewrite_of_same_revision(tmp_path: Path) -> None:
    repository = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "cycle-idempotent.db"))
    first = _append(repository)
    same = _append(repository)
    assert same["cycle_hash"] == first["cycle_hash"]

    radar, journal, devil, changed_cycle = _artifacts(radar_source="athena-mutated")
    with pytest.raises(ValueError, match="Research Cycle distinto"):
        repository.append(
            cycle_payload=changed_cycle.to_api_dict(),
            radar_payload=radar.to_api_dict(),
            journal_payload=journal.to_api_dict(),
            devils_advocate_payload=devil.to_api_dict(),
        )


def test_cycle_repository_detects_direct_package_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "cycle-tamper.db")
    repository = RecommendationProfessionalResearchCycleRepository(database)
    record = _append(repository)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT package_json FROM athena_professional_research_cycles WHERE cycle_hash = ?",
            (record["cycle_hash"],),
        ).fetchone()
        package = json.loads(str(row["package_json"]))
        package["radar"]["candidates"][0]["evidence"][0]["source"] = "tampered-source"
        connection.execute(
            "UPDATE athena_professional_research_cycles SET package_json = ? WHERE cycle_hash = ?",
            (json.dumps(package, sort_keys=True, separators=(",", ":")), record["cycle_hash"]),
        )

    with pytest.raises(ValueError, match="radarHash"):
        repository.get_by_hash(cycle_hash=record["cycle_hash"])


def test_cycle_repository_rejects_fmp_even_if_package_is_otherwise_hash_consistent(tmp_path: Path) -> None:
    repository = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "cycle-fmp.db"))
    radar, journal, devil, cycle = _artifacts(radar_source="Financial Modeling Prep")
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        repository.validate_package(
            cycle_payload=cycle.to_api_dict(),
            radar_payload=radar.to_api_dict(),
            journal_payload=journal.to_api_dict(),
            devils_advocate_payload=devil.to_api_dict(),
        )


def test_cycle_api_persists_complete_package_and_get_reverifies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = AthenaDatabase(tmp_path / "cycle-api.db")
    journal_repository = RecommendationInvestmentJournalRepository(database)
    cycle_repository = RecommendationProfessionalResearchCycleRepository(database)
    monkeypatch.setattr(cycle_api, "journal_repository", journal_repository)
    monkeypatch.setattr(cycle_api, "cycle_repository", cycle_repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_request_payload(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cyclePersistence"]["appendOnly"] is True
    assert data["cyclePersistence"]["packageIntegrityVerified"] is True
    assert data["cyclePersistence"]["cycleHash"] == data["integrity"]["cycleHash"]
    assert data["cyclePersistence"]["storageClaim"] == "tamper_evident_append_only_repository_not_worm_storage"

    fetched = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/{data['integrity']['cycleHash']}"
    )
    assert fetched.status_code == 200
    fetched_data = fetched.json()["data"]
    assert fetched_data["package"]["cycle"]["integrity"]["cycleHash"] == data["integrity"]["cycleHash"]
    assert fetched_data["persistence"]["packageIntegrityVerified"] is True
    assert fetched_data["advisoryStatus"] == "no_advice"
    assert fetched_data["productionEligible"] is False
    assert fetched_data["isWeightingReady"] is False
    assert fetched_data["automaticTrading"] is False


def test_cycle_get_route_is_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}" in paths

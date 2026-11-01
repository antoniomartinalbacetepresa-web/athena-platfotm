"""Offline canonical cycle verification uses real repository fixtures, not mock hashes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_news_synthesis_repository import RecommendationNewsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput, AthenaRadarEvidenceInput, RecommendationAthenaRadarService,
)
from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput, RecommendationDevilsAdvocateService,
)
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput, RecommendationInvestmentJournalService,
)
from app.services.recommendation_news_synthesis_service import (
    NewsModelAssessmentInput, RecommendationNewsSynthesisService,
)
from app.services.recommendation_professional_research_cycle_service import RecommendationProfessionalResearchCycleService
from scripts.verify_persisted_research_cycle_snapshot import _file_hash, main, verify


AS_OF = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
AVAILABLE = AS_OF - timedelta(hours=1)
SOURCE = "https://example.org/issuer-news"


def _snapshot(tmp_path: Path, *, persist_news: bool = True) -> tuple[Path, str]:
    db_path = tmp_path / "operational.db"
    db = AthenaDatabase(db_path)
    radar = RecommendationAthenaRadarService().build(
        as_of=AS_OF,
        candidates=(AthenaRadarCandidateInput(
            instrument_id="issuer:demo", symbol="DEMO",
            evidence=(AthenaRadarEvidenceInput(
                evidence_id="news-1", category="news", urgency="material",
                summary="Synthetic issuer announcement.", available_at=AVAILABLE,
                source="news", source_ref=SOURCE, provider="google_news_rss",
                publisher="Example Wire", published_at=AVAILABLE - timedelta(minutes=1),
            ),),
        ),),
    )
    journal = RecommendationInvestmentJournalService().freeze_snapshot(
        journal_id="journal-demo", revision_id="rev-1", symbol="DEMO",
        recorded_at=AVAILABLE, as_of=AS_OF,
        thesis="Hypothetical research thesis, not investment advice.",
        references=(InvestmentJournalReferenceInput(
            reference_id="ref-1", kind="assumption",
            available_at=AVAILABLE - timedelta(minutes=1),
            source="test-fixture", source_ref="urn:journal:1",
        ),),
    )
    devil = RecommendationDevilsAdvocateService().review(
        journal_id=journal.journal_id, revision_id=journal.revision_id,
        snapshot_hash=journal.snapshot_hash, symbol="DEMO", as_of=AS_OF,
        evidence=(DevilsAdvocateEvidenceInput(
            evidence_id="counter-1", kind="alternative_explanation",
            claim="The reported event may not change cash flows.",
            strength="material", available_at=AVAILABLE,
            source="test-fixture", source_ref="urn:counter:1",
        ),),
    )
    cycle = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="issuer:demo", radar=radar, journal=journal, devils_advocate=devil,
    )
    record = RecommendationProfessionalResearchCycleRepository(db).append(
        cycle_payload=cycle.to_api_dict(), radar_payload=radar.to_api_dict(),
        journal_payload=journal.to_api_dict(), devils_advocate_payload=devil.to_api_dict(),
    )
    if persist_news:
        service = RecommendationNewsSynthesisService()
        evidence = radar.candidates[0].evidence[0]
        news = service.build(
            radar_result=radar,
            assessments=(NewsModelAssessmentInput(
                evidence_id=evidence.evidence_id,
                model_provider="fixture", model_name="test", model_version="v1",
                input_fingerprint=service.evidence_fingerprint(
                    instrument_id="issuer:demo", symbol="DEMO", evidence=evidence,
                ),
                generated_at=AS_OF - timedelta(minutes=10),
                summary="Synthetic news explanation.", importance="low",
                impact_direction="uncertain", impact_magnitude=0.1, confidence=0.2,
            ),),
            minimum_importance="low",
        )
        RecommendationNewsSynthesisRepository(db).append(
            cycle_hash=record["cycle_hash"], radar_hash=record["radar_hash"],
            synthesis_payload=news.to_api_dict(),
        )
    snapshot = tmp_path / "checkpointed-snapshot.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(snapshot) as dest:
        source.backup(dest)
    return snapshot, record["cycle_hash"]


def test_valid_canonical_cycle_and_news_are_verified_without_writes(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    digest = _file_hash(snapshot)
    before = snapshot.read_bytes()
    report = verify(snapshot, expected_sha256=digest, cycle_hash=cycle_hash)
    assert report["status"] == "canonical_snapshot_dependencies_verified"
    assert report["categories"] == ["news"]
    assert report["evidenceCount"] == 1
    assert len(report["snapshotDerivedInputFingerprint"]) == 64
    assert report["readyForNewLocalDraft"] is True
    assert report["sourceAuthenticityIndependentlyVerified"] is False
    assert report["productionEligible"] is False
    assert report["automaticTrading"] is False
    assert snapshot.read_bytes() == before
    assert not Path(str(snapshot) + "-wal").exists()
    assert not Path(str(snapshot) + "-shm").exists()


def test_missing_required_news_fails_closed(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path, persist_news=False)
    with pytest.raises(ValueError, match="Falta la síntesis News"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


def test_snapshot_digest_mismatch_fails_before_database_read(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 del snapshot"):
        verify(snapshot, expected_sha256="0" * 64, cycle_hash=cycle_hash)


def test_tampered_radar_rejected_even_with_new_snapshot_digest(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    with sqlite3.connect(snapshot) as conn:
        package = json.loads(conn.execute(
            "SELECT package_json FROM athena_professional_research_cycles WHERE cycle_hash = ?",
            (cycle_hash,),
        ).fetchone()[0])
        package["radar"]["candidates"][0]["evidence"][0]["summary"] = "TAMPERED"
        conn.execute(
            "UPDATE athena_professional_research_cycles SET package_json = ? WHERE cycle_hash = ?",
            (json.dumps(package), cycle_hash),
        )
    with pytest.raises(ValueError, match="radarHash"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


def test_news_source_binding_rejected_even_if_news_hash_is_recomputed(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    with sqlite3.connect(snapshot) as conn:
        package = json.loads(conn.execute(
            "SELECT package_json FROM athena_news_syntheses WHERE cycle_hash = ?",
            (cycle_hash,),
        ).fetchone()[0])
        for assessment in package["synthesis"]["assessments"]:
            assessment["sourceRef"] = "https://example.org/other-source"
        for item in package["synthesis"]["items"]:
            item["sourceRef"] = "https://example.org/other-source"
        serialized = json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        conn.execute(
            "UPDATE athena_news_syntheses SET package_json = ?, synthesis_hash = ? WHERE cycle_hash = ?",
            (serialized, digest, cycle_hash),
        )
    with pytest.raises(ValueError, match="provenance News"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


def test_cli_rejects_wrong_digest_with_nonzero_exit(tmp_path, capsys):
    snapshot, cycle_hash = _snapshot(tmp_path)
    assert main(["--snapshot", str(snapshot), "--expected-sha256", "f" * 64,
                 "--cycle-hash", cycle_hash]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"

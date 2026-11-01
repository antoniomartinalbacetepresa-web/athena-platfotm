"""Offline canonical cycle verification uses real repository fixtures, not mock hashes."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from app.api.recommendation_athena_synthesis import _canonical_hash, _cycle_evidence_contract, _input_contract
from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_athena_synthesis_repository import RecommendationAthenaSynthesisRepository
from app.services.recommendation_athena_synthesis_service import (
    AthenaSynthesisModelInput, RecommendationAthenaSynthesisService,
)
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


def _snapshot(tmp_path: Path, *, persist_news: bool = True, persist_athena: bool = False) -> tuple[Path, str]:
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
    news_record = None
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
        news_record = RecommendationNewsSynthesisRepository(db).append(
            cycle_hash=record["cycle_hash"], radar_hash=record["radar_hash"],
            synthesis_payload=news.to_api_dict(),
        )
    if persist_athena:
        assert news_record is not None
        input_contract = _input_contract(
            record, news_record, None, _cycle_evidence_contract(record),
        )
        service = RecommendationAthenaSynthesisService()
        payload = service.build(
            cycle_record=record, news_synthesis_record=news_record,
            canonical_input_fingerprint=input_contract["inputFingerprint"],
            model_output=AthenaSynthesisModelInput(
                model_provider="fixture", model_name="test", model_version="v1",
                input_fingerprint=input_contract["inputFingerprint"],
                generated_at=AS_OF + timedelta(minutes=1),
                summary="Synthetic research summary.", rationale="Only frozen evidence.",
                uncertainties=("Unknown future impact.",), evidence_ids=("news-1",),
            ),
        ).to_api_dict()
        payload["outputFingerprint"] = _canonical_hash({
            "inputFingerprint": input_contract["inputFingerprint"],
            "modelProvider": payload["modelProvider"],
            "modelName": payload["modelName"],
            "modelVersion": payload["modelVersion"],
            "generatedAt": payload["generatedAt"],
            "summary": payload["summary"],
            "rationale": payload["rationale"],
            "uncertainties": payload["uncertainties"],
            "evidenceIds": payload["evidenceIds"],
            "investorsSynthesisHash": None,
        })
        RecommendationAthenaSynthesisRepository(db).append(
            cycle_hash=record["cycle_hash"], radar_hash=record["radar_hash"],
            news_synthesis_hash=news_record["synthesis_hash"],
            synthesis_payload=payload,
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
    with closing(sqlite3.connect(snapshot)) as conn:
        package = json.loads(conn.execute(
            "SELECT package_json FROM athena_professional_research_cycles WHERE cycle_hash = ?",
            (cycle_hash,),
        ).fetchone()[0])
        package["radar"]["candidates"][0]["evidence"][0]["summary"] = "TAMPERED"
        conn.execute(
            "UPDATE athena_professional_research_cycles SET package_json = ? WHERE cycle_hash = ?",
            (json.dumps(package), cycle_hash),
        )
        conn.commit()  # Close/checkpoint WAL before verifying the immutable snapshot.
    with pytest.raises(ValueError, match="radarHash"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


def test_news_source_binding_rejected_even_if_news_hash_is_recomputed(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    with closing(sqlite3.connect(snapshot)) as conn:
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
        conn.commit()  # Persist changes to the main database before immutable read.
    with pytest.raises(ValueError, match="provenance News"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


def test_cli_rejects_wrong_digest_with_nonzero_exit(tmp_path, capsys):
    snapshot, cycle_hash = _snapshot(tmp_path)
    assert main(["--snapshot", str(snapshot), "--expected-sha256", "f" * 64,
                 "--cycle-hash", cycle_hash]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_rejects_auxiliary_sqlite_files_even_with_matching_main_file_hash(tmp_path, suffix):
    snapshot, cycle_hash = _snapshot(tmp_path)
    digest = _file_hash(snapshot)
    sidecar = Path(str(snapshot) + suffix)
    sidecar.write_bytes(b"uncheckpointed-or-untrusted-sidecar")
    with pytest.raises(ValueError, match="archivos auxiliares SQLite"):
        verify(snapshot, expected_sha256=digest, cycle_hash=cycle_hash)


def test_committed_uncheckpointed_wal_cannot_hide_tampering_from_immutable_reader(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    main_file_digest = _file_hash(snapshot)
    # Keep the writer open: the committed change lives in the WAL and
    # the SHA-256 of the main database alone remains unchanged.
    with closing(sqlite3.connect(snapshot)) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute("PRAGMA wal_autocheckpoint=0")
        package = json.loads(conn.execute(
            "SELECT package_json FROM athena_professional_research_cycles WHERE cycle_hash = ?",
            (cycle_hash,),
        ).fetchone()[0])
        package["radar"]["candidates"][0]["evidence"][0]["summary"] = "UNTRUSTED WAL CHANGE"
        conn.execute(
            "UPDATE athena_professional_research_cycles SET package_json = ? WHERE cycle_hash = ?",
            (json.dumps(package), cycle_hash),
        )
        conn.commit()
        assert Path(str(snapshot) + "-wal").exists()
        assert _file_hash(snapshot) == main_file_digest
        with pytest.raises(ValueError, match="archivos auxiliares SQLite"):
            verify(snapshot, expected_sha256=main_file_digest, cycle_hash=cycle_hash)


def test_existing_canonical_athena_is_validated_and_blocks_new_draft(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path, persist_athena=True)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    assert report["athenaAlreadyPersisted"] is True
    assert report["persistedAthenaIntegrityVerified"] is True
    assert report["readyForNewLocalDraft"] is False


def test_existing_athena_tampered_hash_is_rejected_not_merely_reported_present(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path, persist_athena=True)
    with closing(sqlite3.connect(snapshot)) as conn:
        conn.execute(
            "UPDATE athena_research_syntheses SET synthesis_hash = ? WHERE cycle_hash = ?",
            ("0" * 64, cycle_hash),
        )
        conn.commit()
    with pytest.raises(ValueError, match="synthesis_hash"):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


@pytest.mark.parametrize("field,invalid,expected_error", [
    ("inputFingerprint", "0" * 64, "contrato canónico"),
    ("outputFingerprint", "0" * 64, "outputFingerprint"),
    ("generatedAt", (AS_OF - timedelta(minutes=1)).isoformat(), "contrato canónico"),
])
def test_existing_athena_rehashed_package_still_must_match_canonical_contract(
    tmp_path, field, invalid, expected_error,
):
    snapshot, cycle_hash = _snapshot(tmp_path, persist_athena=True)
    with closing(sqlite3.connect(snapshot)) as conn:
        package = json.loads(conn.execute(
            "SELECT package_json FROM athena_research_syntheses WHERE cycle_hash = ?",
            (cycle_hash,),
        ).fetchone()[0])
        package["synthesis"][field] = invalid
        conn.execute(
            "UPDATE athena_research_syntheses SET package_json = ?, synthesis_hash = ? WHERE cycle_hash = ?",
            (json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
             _canonical_hash(package), cycle_hash),
        )
        conn.commit()
    with pytest.raises(ValueError, match=expected_error):
        verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)


# Deployed comparison is a read-only gate, not a model execution or promotion.
from scripts import compare_deployed_research_input_contract as deployed_gate


def _deployed_contract_for(report, snapshot):
    # Reconstruct the exact deployed API binding from the persisted fixture.
    # A fake artifactHash-only provenance must never pass this gate.
    with closing(sqlite3.connect(snapshot)) as conn:
        row = conn.execute(
            "SELECT package_json FROM athena_news_syntheses WHERE cycle_hash = ?",
            (report["cycleHash"],),
        ).fetchone()
    assessments = json.loads(row[0])["synthesis"]["assessments"]
    bindings = sorted((
        {
            "evidenceId": str(item["evidenceId"]).strip(),
            "assessmentFingerprint": str(item["assessmentFingerprint"]).strip().lower(),
            "sourceRef": str(item["sourceRef"]).strip(),
        }
        for item in assessments
    ), key=lambda item: item["evidenceId"])
    return {
        "cycleHash": report["cycleHash"],
        "radarHash": report["radarHash"],
        "newsSynthesisHash": report["newsSynthesisHash"],
        "inputFingerprint": report["snapshotDerivedInputFingerprint"],
        "inputAsOf": report["inputAsOf"],
        "evidenceIds": ["news-1"],
        "coveredCategories": ["news"],
        "newsProvenance": {
            "artifactHash": report["newsSynthesisHash"],
            "artifactType": "canonical_news_synthesis",
            "assessmentBindings": bindings,
            "userFacingTraceability": True,
            "recommendationInfluence": False,
            "automaticTrading": False,
        },
        "advisoryStatus": "no_advice",
        "recommendationInfluence": False,
        "automaticTrading": False,
    }


def test_deployed_contract_matches_verified_snapshot_without_writes(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    digest = _file_hash(snapshot)
    report = verify(snapshot, expected_sha256=digest, cycle_hash=cycle_hash)
    before = snapshot.read_bytes()
    result = deployed_gate.compare_contract(report, _deployed_contract_for(report, snapshot))
    assert result["status"] == "snapshot_deployed_input_contract_matched"
    assert result["readyForNewLocalDraft"] is True
    assert result["deployedPersistenceVerified"] is False
    assert result["modelExecutionVerified"] is False
    assert result["productionEligible"] is False
    assert snapshot.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("inputFingerprint", "0" * 64),
    ("radarHash", "0" * 64),
    ("newsSynthesisHash", "0" * 64),
    ("inputAsOf", (AS_OF + timedelta(days=1)).isoformat()),
    ("evidenceIds", ["different-news-id"]),
    ("evidenceIds", ["news-1", "news-1"]),
    ("coveredCategories", ["investors"]),
    ("advisoryStatus", "advice"),
    ("recommendationInfluence", True),
    ("automaticTrading", True),
])
def test_deployed_contract_mismatch_fails_closed(tmp_path, field, value):
    snapshot, cycle_hash = _snapshot(tmp_path)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    live = _deployed_contract_for(report, snapshot)
    live[field] = value
    with pytest.raises(ValueError):
        deployed_gate.compare_contract(report, live)


def test_deployed_gate_rejects_missing_news_provenance(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    live = _deployed_contract_for(report, snapshot)
    del live["newsProvenance"]
    with pytest.raises(ValueError, match="provenance"):
        deployed_gate.compare_contract(report, live)


def test_deployed_gate_does_not_allow_redrafting_existing_athena(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path, persist_athena=True)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    result = deployed_gate.compare_contract(report, _deployed_contract_for(report, snapshot))
    assert result["athenaAlreadyPersistedInSnapshot"] is True
    assert result["readyForNewLocalDraft"] is False


@pytest.mark.parametrize("origin,allow", [
    ("http://example.org", False),
    ("http://localhost:8000", True),
    ("http://127.0.0.2:8000", True),
    ("https://example.org/other-path", False),
    ("https://user:secret@example.org", False),
    ("https://example.org?token=secret", False),
])
def test_deployed_gate_rejects_unsafe_origins(origin, allow):
    with pytest.raises(ValueError):
        deployed_gate._validated_origin(origin, allow_loopback_http=allow)


def test_deployed_gate_loopback_requires_explicit_opt_in():
    with pytest.raises(ValueError):
        deployed_gate._validated_origin("http://127.0.0.1:8000", allow_loopback_http=False)
    assert deployed_gate._validated_origin(
        "http://127.0.0.1:8000", allow_loopback_http=True
    ) == "http://127.0.0.1:8000"


def test_deployed_gate_cli_reports_match_with_stubbed_network(tmp_path, monkeypatch, capsys):
    snapshot, cycle_hash = _snapshot(tmp_path)
    digest = _file_hash(snapshot)
    report = verify(snapshot, expected_sha256=digest, cycle_hash=cycle_hash)
    monkeypatch.setattr(
        deployed_gate, "fetch_deployed_contract",
        lambda **kwargs: _deployed_contract_for(report, snapshot),
    )
    assert deployed_gate.main([
        "--snapshot", str(snapshot), "--expected-sha256", digest,
        "--cycle-hash", cycle_hash, "--backend-origin", "https://example.org",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["productionEligible"] is False


def test_deployed_gate_cli_rejects_live_mismatch(tmp_path, monkeypatch, capsys):
    snapshot, cycle_hash = _snapshot(tmp_path)
    digest = _file_hash(snapshot)
    report = verify(snapshot, expected_sha256=digest, cycle_hash=cycle_hash)
    live = _deployed_contract_for(report, snapshot)
    live["inputFingerprint"] = "f" * 64
    monkeypatch.setattr(deployed_gate, "fetch_deployed_contract", lambda **kwargs: live)
    assert deployed_gate.main([
        "--snapshot", str(snapshot), "--expected-sha256", digest,
        "--cycle-hash", cycle_hash, "--backend-origin", "https://example.org",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize("field,replacement", [
    ("artifactType", "untrusted_news"),
    ("assessmentBindings", []),
    ("userFacingTraceability", False),
    ("recommendationInfluence", True),
    ("automaticTrading", True),
])
def test_deployed_gate_rejects_modified_news_provenance_binding(
    tmp_path, field, replacement,
):
    snapshot, cycle_hash = _snapshot(tmp_path)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    deployed = _deployed_contract_for(report, snapshot)
    deployed["newsProvenance"][field] = replacement
    with pytest.raises(ValueError, match="provenance news"):
        deployed_gate.compare_contract(report, deployed)


def test_deployed_gate_rejects_modified_assessment_source_with_same_artifact_hash(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    deployed = _deployed_contract_for(report, snapshot)
    deployed["newsProvenance"]["assessmentBindings"][0]["sourceRef"] = (
        "https://example.org/forged-source"
    )
    with pytest.raises(ValueError, match="provenance news"):
        deployed_gate.compare_contract(report, deployed)


def test_deployed_gate_rejects_missing_snapshot_provenance_digest(tmp_path):
    snapshot, cycle_hash = _snapshot(tmp_path)
    report = verify(snapshot, expected_sha256=_file_hash(snapshot), cycle_hash=cycle_hash)
    report.pop("newsProvenanceSha256")
    with pytest.raises(ValueError, match="provenance news"):
        deployed_gate.compare_contract(report, _deployed_contract_for(report, snapshot))

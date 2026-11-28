"""Owner-bound Investors synthesis using synthetic canonical evidence only."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

import app.api.recommendation_investors_synthesis as investors_api
import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_investors_synthesis_repository import RecommendationInvestorsSynthesisRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.recommendation_investors_synthesis_service import RecommendationInvestorsSynthesisService
from test_recommendation_professional_research_cycle_external_provenance_api import _payload


PREFIX = "/api/v1/recommendations/professional-research/research-cycle"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    database = AthenaDatabase(tmp_path / "private-investors-synthetic.db")
    cycles = RecommendationProfessionalResearchCycleRepository(database)
    journals = RecommendationInvestmentJournalRepository(database)
    syntheses = RecommendationInvestorsSynthesisRepository(database)
    monkeypatch.setattr(cycle_api, "cycle_repository", cycles)
    monkeypatch.setattr(cycle_api, "journal_repository", journals)
    monkeypatch.setattr(investors_api, "cycle_repository", cycles)
    monkeypatch.setattr(investors_api, "synthesis_repository", syntheses)
    monkeypatch.setitem(app.dependency_overrides, investors_api.current_account, lambda: {"id": 17})
    syntheses.initialize()

    def create_cycle(owner_id=17, *, public=False):
        payload = _payload(category="investors", provider="synthetic_issuer_ir", publisher="Synthetic issuer")
        payload["journalId"] = ("synthetic-public-investors" if public
                                else f"__athena_private_owner_{owner_id}__:synthetic-investors")
        result = cycle_api._persist_professional_research_cycle(
            cycle_api.ProfessionalResearchCycleRequest(**payload),
            **({} if public else {"owner_id": owner_id}),
        )
        return result["data"]["integrity"]["cycleHash"]

    cycle_hash = create_cycle()
    record = cycles.get_by_hash(cycle_hash=cycle_hash, owner_id=17)
    radar = investors_api._radar_from_cycle_record(record)
    candidate = radar.candidates[0]
    evidence = candidate.evidence[0]
    fingerprint = RecommendationInvestorsSynthesisService().evidence_fingerprint(
        instrument_id=candidate.instrument_id, symbol=candidate.symbol, evidence=evidence,
    )
    request = {"assessments": [{
        "evidenceId": evidence.evidence_id,
        "modelProvider": "synthetic_model_provider", "modelName": "synthetic-investors",
        "modelVersion": "test-only", "inputFingerprint": fingerprint,
        "generatedAt": record["as_of"], "summary": "Synthetic delayed filing context; human review required.",
        "importance": "medium", "impactDirection": "uncertain", "impactMagnitude": 0.3, "confidence": 0.4,
    }]}
    return database, TestClient(app), cycle_hash, request, create_cycle


def count(database):
    with database.connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM athena_investors_syntheses").fetchone()[0]


def test_owner_can_write_read_and_retry_without_public_artifact_exposure(setup):
    database, client, cycle_hash, request, _ = setup
    private = f"{PREFIX}/private/{cycle_hash}/investors-synthesis"
    public = f"{PREFIX}/{cycle_hash}/investors-synthesis"
    saved = client.post(private, json=request)
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["cycleBindingVerified"] is True
    assert data["cycleHash"] == cycle_hash
    assert data["synthesis"]["modelExecutionVerified"] is False
    assert data["synthesis"]["productionTruthClaimed"] is False
    assert data["automaticTrading"] is data["automaticScoring"] is data["recommendationInfluence"] is False
    assert data["provenance"]["artifactHash"] == data["persistence"]["synthesisHash"]
    assert client.post(private, json=request).json() == saved.json()
    read = client.get(private)
    assert read.status_code == 200
    assert read.json() == saved.json()
    assert count(database) == 1
    # Preserve the legacy public contracts: no public fallback for private cycles.
    assert client.get(public).status_code == 404
    assert client.post(public, json=request).status_code == 400
    assert count(database) == 1


def test_other_owner_is_rejected_before_any_synthesis_read_or_write(setup, monkeypatch):
    database, client, cycle_hash, request, _ = setup
    monkeypatch.setitem(app.dependency_overrides, investors_api.current_account, lambda: {"id": 23})
    def unexpected(**_):
        pytest.fail("another owner reached the artifact store")
    monkeypatch.setattr(investors_api.synthesis_repository, "append", unexpected)
    monkeypatch.setattr(investors_api.synthesis_repository, "get_by_cycle_hash", unexpected)
    path = f"{PREFIX}/private/{cycle_hash}/investors-synthesis"
    denied = client.get(path)
    absent = client.get(f"{PREFIX}/private/{'0' * 64}/investors-synthesis")
    assert denied.status_code == absent.status_code == 404
    assert denied.json() == absent.json()
    assert client.post(path, json=request).status_code == 404
    assert count(database) == 0


def test_authentication_precedes_cycle_and_artifact_access(setup, monkeypatch):
    database, client, cycle_hash, request, _ = setup
    monkeypatch.delitem(app.dependency_overrides, investors_api.current_account)
    def unexpected(**_):
        pytest.fail("anonymous request reached persisted research")
    monkeypatch.setattr(investors_api.cycle_repository, "get_by_hash", unexpected)
    monkeypatch.setattr(investors_api.synthesis_repository, "append", unexpected)
    monkeypatch.setattr(investors_api.synthesis_repository, "get_by_cycle_hash", unexpected)
    path = f"{PREFIX}/private/{cycle_hash}/investors-synthesis"
    assert client.get(path).status_code == 401
    assert client.post(path, json=request).status_code == 401
    assert count(database) == 0


def test_two_owners_have_separate_cycle_bindings_and_artifacts(setup, monkeypatch):
    database, client, first, request, create_cycle = setup
    second = create_cycle(owner_id=23)
    one = f"{PREFIX}/private/{first}/investors-synthesis"
    two = f"{PREFIX}/private/{second}/investors-synthesis"
    assert client.post(one, json=request).status_code == 200
    assert client.get(two).status_code == 404
    monkeypatch.setitem(app.dependency_overrides, investors_api.current_account, lambda: {"id": 23})
    saved = client.post(two, json=request)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["cycleHash"] == second
    assert client.get(one).status_code == 404
    assert client.get(two).status_code == 200
    assert count(database) == 2


def test_existing_public_synthesis_contract_remains_available_for_public_cycle(setup):
    database, client, _, request, create_cycle = setup
    public_hash = create_cycle(public=True)
    public = f"{PREFIX}/{public_hash}/investors-synthesis"
    saved = client.post(public, json=request)
    assert saved.status_code == 200, saved.text
    assert client.get(public).json() == saved.json()
    assert client.get(f"{PREFIX}/private/{public_hash}/investors-synthesis").status_code == 404
    assert count(database) == 1


def test_private_synthesis_rejects_replacement_and_tampering(setup):
    database, client, cycle_hash, request, _ = setup
    path = f"{PREFIX}/private/{cycle_hash}/investors-synthesis"
    first = client.post(path, json=request)
    assert first.status_code == 200
    changed = json.loads(json.dumps(request))
    changed["assessments"][0]["summary"] = "Different external model interpretation."
    assert client.post(path, json=changed).status_code == 400
    assert client.get(path).json() == first.json()
    with database.connect() as connection:
        row = connection.execute("SELECT package_json FROM athena_investors_syntheses").fetchone()
        package = json.loads(row[0])
        package["synthesis"]["assessments"][0]["summary"] = "synthetic-private-mutated-secret"
        connection.execute("UPDATE athena_investors_syntheses SET package_json = ?", (json.dumps(package),))
    invalid = client.get(path)
    assert invalid.status_code == 404
    assert "synthetic-private-mutated-secret" not in invalid.text

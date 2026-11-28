"""Synthetic history -> canonical Radar/Journal/Cycle, with atomic private binding."""
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app.api import recommendation_professional_research_cycle as api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.repositories.persisted_market_research_reference_repository import PersistedMarketResearchReferenceRepository
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.services.persisted_market_history_service import PersistedMarketHistoryService


NOW = datetime(2026, 11, 26, 15, tzinfo=timezone.utc)
POST = "/api/v1/recommendations/professional-research/research-cycle/from-persisted-market-history"
GET_REF = "/api/v1/recommendations/professional-research/market-history-reference/private/"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    database = AthenaDatabase(tmp_path / "synthetic-market-cycle.db")
    database.initialize()
    instrument = InstrumentRepository(database).upsert({
        "symbol": "SYNTH", "companyName": "Synthetic bridge fixture",
        "exchangeShortName": "TEST", "currency": "USD", "instrumentType": "common_stock",
    })
    observations = [{"timestamp": NOW - timedelta(days=3), "open": 99,
                     "high": 103, "low": 98, "close": 101, "volume": 200}]
    MarketObservationRepository(database).save_many(
        instrument_id=instrument, observations=observations,
        source_provider="synthetic_fixture", retrieved_at=NOW - timedelta(days=2),
    )
    journal = RecommendationInvestmentJournalRepository(database)
    cycle = RecommendationProfessionalResearchCycleRepository(database)
    reference = PersistedMarketResearchReferenceRepository(database)
    for repository in (journal, cycle, reference):
        repository.initialize()
    monkeypatch.setattr(api, "journal_repository", journal)
    monkeypatch.setattr(api, "cycle_repository", cycle)
    monkeypatch.setattr(api, "market_reference_repository", reference)
    monkeypatch.setattr(api, "persisted_history_service", PersistedMarketHistoryService(database))
    monkeypatch.setitem(app.dependency_overrides, api.current_account, lambda: {"id": 17})
    prior = (NOW - timedelta(days=2)).isoformat()
    payload = {
        "instrumentId": instrument, "symbol": "SYNTH", "sourceProvider": "synthetic_fixture",
        "observedFrom": (NOW - timedelta(days=5)).isoformat(), "observedTo": NOW.isoformat(),
        "asOf": NOW.isoformat(), "recordedAt": NOW.isoformat(),
        "journalId": "synthetic-history-review", "revisionId": "r1",
        "thesis": "Human question about synthetic data quality, not a trade recommendation.",
        "journalReferences": [{"referenceId": "human-assumption", "kind": "assumption",
            "availableAt": prior, "source": "human_research", "sourceRef": "urn:human:assumption"}],
        "contradictoryEvidence": [{"evidenceId": "human-contradiction", "kind": "alternative_explanation",
            "claim": "Synthetic prices cannot establish market behavior.", "strength": "material",
            "availableAt": prior, "source": "human_research", "sourceRef": "urn:human:objection"}],
    }
    return database, payload, TestClient(app)


def counts(database):
    with database.connect() as connection:
        return [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "athena_market_research_references", "athena_investment_journal_snapshots",
            "athena_professional_research_cycles")]


def test_history_cycle_is_private_idempotent_and_canonically_bound_without_copying_prices(setup):
    database, payload, client = setup
    first = client.post(POST, json=payload)
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    reference = data["marketHistoryReference"]
    assert reference["evidenceKind"] == "synthetic_fixture"
    assert reference["metadataOnly"] is True
    assert reference["licenceVerified"] is reference["historicalPointInTimeEligible"] is False
    assert data["productionEligible"] is data["policy"]["automaticTrading"] is False
    assert data["researchUrgency"] == "routine"
    second = client.post(POST, json=payload)
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert counts(database) == [1, 1, 1]
    cycle_hash = data["integrity"]["cycleHash"]
    public = client.get(f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}")
    assert public.status_code == 404
    private = client.get(f"/api/v1/recommendations/professional-research/research-cycle/private/{cycle_hash}")
    assert private.status_code == 200
    package = private.json()["data"]["package"]
    radar = package["radar"]["candidates"][0]["evidence"][0]
    assert radar["category"] == "data_quality"
    assert radar["sourceRef"] == reference["sourceRef"]
    assert "SYNTHETIC FIXTURE" in radar["summary"]
    assert any(item["sourceRef"] == reference["sourceRef"] for item in package["journal"]["references"])
    snapshot = client.get(GET_REF + reference["referenceHash"])
    assert snapshot.status_code == 200
    stored = snapshot.json()["data"]["reference"]
    assert stored["evidenceKind"] == "synthetic_fixture"
    assert stored["classificationBasis"] == "declared_source_name_not_independent_attestation"
    assert stored["observations"][0]["observationId"] > 0
    assert len(stored["observations"][0]["rowHash"]) == 64
    assert not {"close", "open", "high", "low", "volume"}.intersection(stored["observations"][0])


def test_snapshot_and_cycle_cannot_be_read_by_another_owner(setup, monkeypatch):
    _, payload, client = setup
    result = client.post(POST, json=payload).json()["data"]
    monkeypatch.setitem(app.dependency_overrides, api.current_account, lambda: {"id": 18})
    assert client.get(GET_REF + result["marketHistoryReference"]["referenceHash"]).status_code == 404
    assert client.get("/api/v1/recommendations/professional-research/research-cycle/private/"
                      + result["integrity"]["cycleHash"]).status_code == 404


def test_authentication_precedes_history_access(setup, monkeypatch):
    database, payload, client = setup
    monkeypatch.delitem(app.dependency_overrides, api.current_account)
    def unexpected(**_):
        pytest.fail("unauthenticated request reached history")
    monkeypatch.setattr(api.persisted_history_service, "get_history", unexpected)
    assert client.post(POST, json=payload).status_code == 401
    assert counts(database) == [0, 0, 0]


@pytest.mark.parametrize("field,value", [
    ("licenceVerified", True), ("productionEligible", True),
    ("referenceHash", "a" * 64), ("observations", [{"close": 1}]),
    ("instrumentId", True), ("limit", True),
])
def test_client_cannot_supply_prices_hashes_or_authority(setup, field, value):
    database, payload, client = setup
    assert client.post(POST, json=payload | {field: value}).status_code == 422
    assert counts(database) == [0, 0, 0]


@pytest.mark.parametrize("field,value,status", [
    ("symbol", "OTHER", 400), ("instrumentId", 999, 404),
    ("sourceProvider", "twelve_data", 400), ("sourceProvider", "yahoo", 409),
    ("asOf", "2026-11-24T14:59:59.999999+00:00", 400),
])
def test_invalid_selection_cannot_write_research(setup, field, value, status):
    database, payload, client = setup
    assert client.post(POST, json=payload | {field: value}).status_code == status
    assert counts(database) == [0, 0, 0]


def test_cutoff_before_retrieval_is_empty_and_writes_nothing(setup):
    database, payload, client = setup
    cutoff = NOW - timedelta(days=2, microseconds=1)
    change = {"asOf": cutoff.isoformat(), "observedTo": cutoff.isoformat(), "recordedAt": cutoff.isoformat()}
    assert client.post(POST, json=payload | change).status_code == 409
    assert counts(database) == [0, 0, 0]


def test_cycle_failure_rolls_back_reference_and_journal_together(setup, monkeypatch):
    database, payload, client = setup
    def fail(**_):
        raise RuntimeError("synthetic-private-database-location")
    monkeypatch.setattr(api.cycle_repository, "append", fail)
    response = client.post(POST, json=payload)
    assert response.status_code == 500
    assert "synthetic-private" not in response.text
    assert counts(database) == [0, 0, 0]


def test_re_read_rejects_reference_json_and_underlying_row_tampering(setup):
    database, payload, client = setup
    result = client.post(POST, json=payload).json()["data"]
    digest = result["marketHistoryReference"]["referenceHash"]
    with database.connect() as connection:
        connection.execute("UPDATE market_observations SET close = 102")
    assert client.get(GET_REF + digest).status_code == 503
    assert client.get("/api/v1/recommendations/professional-research/research-cycle/private/"
                      + result["integrity"]["cycleHash"]).status_code == 500
    with database.connect() as connection:
        connection.execute("UPDATE market_observations SET close = 101")
    assert client.get(GET_REF + digest).status_code == 200
    with database.connect() as connection:
        row = connection.execute("SELECT reference_json FROM athena_market_research_references").fetchone()
        reference = json.loads(row[0])
        reference["productionEligible"] = True
        connection.execute("UPDATE athena_market_research_references SET reference_json = ?", (json.dumps(reference),))
    assert client.get(GET_REF + digest).status_code == 503


def test_changed_evidence_cannot_overwrite_a_journal_revision(setup):
    database, payload, client = setup
    assert client.post(POST, json=payload).status_code == 200
    with database.connect() as connection:
        connection.execute("UPDATE market_observations SET close = 102")
    response = client.post(POST, json=payload)
    assert response.status_code == 400
    assert counts(database) == [1, 1, 1]


def test_unverified_rows_are_not_copied_into_research_reference_storage(setup):
    database, payload, client = setup
    # This is still a synthetic test fixture; the declared provider lacks a
    # fixture classification and cannot enter the fixture-only write bridge.
    MarketObservationRepository(database).save_many(
        instrument_id=payload["instrumentId"],
        observations=[{"timestamp": NOW - timedelta(days=3), "close": 101}],
        source_provider="unverified_provider", retrieved_at=NOW - timedelta(days=2),
    )
    response = client.post(POST, json=payload | {"sourceProvider": "unverified_provider"})
    assert response.status_code == 409
    assert counts(database) == [0, 0, 0]


def test_reserved_reference_cannot_be_forged_via_legacy_public_cycle(setup):
    database, payload, client = setup
    standard = {key: value for key, value in payload.items()
                if key not in {"sourceProvider", "observedFrom", "observedTo"}}
    standard["instrumentId"] = str(payload["instrumentId"])
    standard["radarEvidence"] = [{
        "evidenceId": "forged-attachment", "category": "data_quality", "urgency": "routine",
        "summary": "Client cannot certify a server reference.", "availableAt": payload["asOf"],
        "source": "human_research", "sourceRef": "urn:athena:market-history:" + "a" * 64,
    }]
    response = client.post("/api/v1/recommendations/professional-research/research-cycle", json=standard)
    assert response.status_code == 400
    assert counts(database) == [0, 0, 0]


def test_row_change_between_selection_and_transaction_is_rejected_atomically(setup, monkeypatch):
    database, payload, client = setup
    original = api.market_reference_repository.append
    def change_then_append(reference, *, owner_id, connection):
        connection.execute("UPDATE market_observations SET close = 102")
        return original(reference, owner_id=owner_id, connection=connection)
    monkeypatch.setattr(api.market_reference_repository, "append", change_then_append)
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == [0, 0, 0]
    with database.connect() as connection:
        assert connection.execute("SELECT close FROM market_observations").fetchone()[0] == 101


@pytest.mark.parametrize("field", ["journalReferences", "contradictoryEvidence"])
@pytest.mark.parametrize("prefix", ["urn:athena:market-history:", "URN:ATHENA:MARKET-HISTORY:",
                                   "urn%3Aathena%3Amarket-history%3A"])
def test_client_cannot_add_another_reserved_attachment_anywhere(setup, field, prefix):
    database, payload, client = setup
    payload[field][0]["sourceRef"] = prefix + "a" * 64
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == [0, 0, 0]


def test_identical_row_ids_in_another_database_cannot_be_rebound(setup, tmp_path, monkeypatch):
    database, payload, client = setup
    other = AthenaDatabase(tmp_path / "other-synthetic-history.db")
    other.initialize()
    instrument = InstrumentRepository(other).upsert({
        "symbol": "SYNTH", "companyName": "Synthetic bridge fixture",
        "exchangeShortName": "TEST", "currency": "USD", "instrumentType": "common_stock",
    })
    assert instrument == payload["instrumentId"]
    MarketObservationRepository(other).save_many(
        instrument_id=instrument,
        observations=[{"timestamp": NOW - timedelta(days=3), "close": 999}],
        source_provider="synthetic_fixture", retrieved_at=NOW - timedelta(days=2),
    )
    monkeypatch.setattr(api, "persisted_history_service", PersistedMarketHistoryService(other))
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == [0, 0, 0]


@pytest.mark.parametrize("column,value", [
    ("close", 102), ("close", -1), ("high", 1), ("volume", -1),
    ("source_timestamp", (NOW + timedelta(days=1)).isoformat()),
])
def test_changed_rows_before_reference_capture_cannot_be_laundered(setup, monkeypatch, column, value):
    database, payload, client = setup
    original = api.market_reference_repository.build
    def change_then_build(history):
        # Independent writer commits after projection but before capture.
        # Its change must not acquire a valid reference to the earlier selection.
        with database.connect() as connection:
            connection.execute(f"UPDATE market_observations SET {column} = ?", (value,))
        return original(history)
    monkeypatch.setattr(api.market_reference_repository, "build", change_then_build)
    assert client.post(POST, json=payload).status_code == 400
    assert counts(database) == [0, 0, 0]


def test_unrelated_schema_addition_does_not_change_reference_content_hash(setup):
    database, payload, client = setup
    data = client.post(POST, json=payload).json()["data"]
    digest = data["marketHistoryReference"]["referenceHash"]
    with database.connect() as connection:
        connection.execute("ALTER TABLE market_observations ADD COLUMN synthetic_note TEXT DEFAULT 'not-evidence'")
    assert client.get(GET_REF + digest).status_code == 200

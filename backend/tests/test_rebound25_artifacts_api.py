"""Durable server-only artificial strategy artifacts; no provider/account calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import rebound25_artifacts as api
from app.api.rebound25_synthetic import Rebound25ParametersRequest
from app.database.athena_database import AthenaDatabase
from app.repositories.rebound25_artifact_repository import FIXTURE_ID, artifact_hash, canonical_json
from app.services.rebound25_artifact_service import Rebound25ArtifactService

PATH = "/api/v1/research/strategies/rebound25/artifacts"
PARAMETERS = {"takeProfitPct": 2.0, "stopLossPct": 1.0, "maxHoldingSessions": 5,
    "commissionBps": 1.0, "spreadBps": 10.0, "slippageBps": 5.0, "orderUnits": 1.0,
    "minAverageVolume": 1.0, "maxVolumeParticipation": 0.01, "minRelativeVolume": 0.0}

@pytest.fixture
def setup(tmp_path, monkeypatch):
    database = AthenaDatabase(tmp_path / "server-only-synthetic-artifacts.db")
    service = Rebound25ArtifactService(database)
    service.initialize()
    monkeypatch.setattr(api, "artifact_service", service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.current_account] = lambda: {"id": 17}
    return database, service, app, TestClient(app)

def payload():
    return {"fixtureId": FIXTURE_ID, "parameters": deepcopy(PARAMETERS)}

def count(database):
    with database.connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM athena_rebound25_synthetic_artifacts").fetchone()[0]

def test_create_replay_reopen_and_index_preserve_owner_and_original_availability(setup):
    database, _, _, client = setup
    first = client.post(PATH, json=payload())
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["ownerBindingVerified"] is data["serverFixtureGenerated"] is True
    assert data["fixtureId"] == FIXTURE_ID and data["evidenceKind"] == "synthetic_fixture"
    for field in ("automaticTrading", "ordersEnabled", "productionEligible", "licenseVerified", "outOfSampleValidated"):
        assert data[field] is False
    assert data["request"]["instrumentId"] == "SYNTHETIC-LAB-25"
    assert len(data["request"]["bars"]) == 40 and data["request"]["bars"][0]["high"] == 102.0
    assert data["result"]["closedTradeCount"] == 1
    assert data["result"]["trades"][0]["exitReason"] == "stop_first_ambiguous_daily_bar"
    assert datetime.fromisoformat(data["createdAt"]) > datetime.fromisoformat(data["result"]["asOf"])
    assert client.post(PATH, json=payload()).json() == first.json() and count(database) == 1
    restarted = Rebound25ArtifactService(AthenaDatabase(database.database_path))
    assert restarted.get(owner_id=17, artifact_hash=data["artifactHash"]) == data
    assert client.get(PATH + "/" + data["artifactHash"]).json()["data"] == data
    index = client.get(PATH).json()["data"]
    assert index["returnedCount"] == 1
    assert index["metadataOnly"] is index["readOnly"] is index["ownerBindingVerified"] is True
    assert index["items"] == [{key: data[key] for key in ("artifactHash", "fixtureId", "createdAt")}]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 0

def test_omitted_and_explicit_defaults_share_one_artifact(setup):
    database, _, _, client = setup
    first = client.post(PATH, json=payload())
    explicit = {**PARAMETERS, "lookbackSessions": 25, "minReboundPct": 1.0,
                "maxConfirmationSessions": 3, "version": "rebound25-synthetic-v1"}
    second = client.post(PATH, json={"fixtureId": FIXTURE_ID, "parameters": explicit})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and count(database) == 1


def test_other_owner_cannot_read_or_deserialize_and_has_distinct_identity(setup, monkeypatch):
    database, service, app, client = setup
    first = client.post(PATH, json=payload()).json()["data"]
    app.dependency_overrides[api.current_account] = lambda: {"id": 18}
    original = service.repository._read
    monkeypatch.setattr(service.repository, "_read", lambda *_, **__: pytest.fail("Other owner deserialized"))
    assert client.get(PATH + "/" + first["artifactHash"]).status_code == 404
    assert client.get(PATH).json()["data"]["items"] == []
    monkeypatch.setattr(service.repository, "_read", original)
    second = client.post(PATH, json=payload()).json()["data"]
    assert second["artifactHash"] != first["artifactHash"] and count(database) == 2
    assert client.get(PATH).json()["data"]["items"][0]["artifactHash"] == second["artifactHash"]

@pytest.mark.parametrize("method,path", [("post", PATH), ("get", PATH), ("get", PATH + "/" + "a" * 64)])
def test_authentication_precedes_calculation_or_storage(setup, monkeypatch, method, path):
    _, service, app, client = setup
    app.dependency_overrides.clear()
    for operation in ("create", "list", "get"):
        monkeypatch.setattr(service, operation, lambda **_: pytest.fail("Unauthenticated access"))
    response = client.post(path, json=payload()) if method == "post" else client.get(path)
    assert response.status_code == 401

@pytest.mark.parametrize("owner", [True, 0, -1, "17", None])
def test_invalid_owner_fails_before_calculation(setup, monkeypatch, owner):
    _, service, app, client = setup
    app.dependency_overrides[api.current_account] = lambda: {"id": owner}
    monkeypatch.setattr(service, "create", lambda **_: pytest.fail("Invalid owner evaluated"))
    assert client.post(PATH, json=payload()).status_code == 401

@pytest.mark.parametrize("extra", [{"bars": []}, {"request": {}}, {"result": {}}, {"ownerId": 18},
    {"createdAt": "2026-01-01T00:00:00Z"}, {"artifactHash": "a" * 64},
    {"licenseVerified": True}, {"sourceProvider": "twelve_data"}])
def test_client_prices_hashes_owner_and_rights_flags_are_not_persistable(setup, extra):
    database, _, _, client = setup
    assert client.post(PATH, json={**payload(), **extra}).status_code == 422
    assert count(database) == 0

@pytest.mark.parametrize("change", [{"fixtureId": "real-market-history"},
    {"parameters": {**PARAMETERS, "orderUnits": True}},
    {"parameters": {**PARAMETERS, "stopLossPct": "1"}},
    {"parameters": {**PARAMETERS, "maxHoldingSessions": 5.0}},
    {"parameters": {**PARAMETERS, "bars": []}}])
def test_unknown_fixture_and_coercions_are_rejected_without_write(setup, change):
    database, _, _, client = setup
    assert client.post(PATH, json={**payload(), **change}).status_code == 422
    assert count(database) == 0

def test_invalid_algorithm_parameters_leave_no_record(setup):
    database, _, _, client = setup
    response = client.post(PATH, json={"fixtureId": FIXTURE_ID,
        "parameters": {**PARAMETERS, "spreadBps": 20000.0}})
    assert response.status_code == 400 and count(database) == 0

def test_validation_failure_rolls_back_insert_inside_write_transaction(setup, monkeypatch):
    database, service, _, client = setup
    def fail(_):
        raise ValueError("Synthetic validation failure")
    monkeypatch.setattr(service, "_validate", fail)
    assert client.post(PATH, json=payload()).status_code == 400
    assert count(database) == 0

def test_external_transaction_rollback_preserves_atomicity(setup):
    database, service, _, _ = setup
    from app.services.rebound25_artifact_service import build_server_rebound25_fixture
    request = build_server_rebound25_fixture(Rebound25ParametersRequest.model_validate(PARAMETERS))
    result = service._calculate(request)
    with pytest.raises(RuntimeError):
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            service.repository.append(owner_id=17, fixture_id=FIXTURE_ID, request=request,
                                      result=result, connection=connection)
            raise RuntimeError("Synthetic transaction abort")
    assert count(database) == 0

@pytest.mark.parametrize("column,value", [("result_json", '{"synthetic":"tampered"}'),
    ("request_json", '{"bars":[]}'), ("created_at", "2026-01-01T00:00:00+00:00"),
    ("fixture_id", "unapproved-fixture")])
def test_stored_row_tampering_rejects_detail_and_index(setup, column, value):
    database, _, _, client = setup
    digest = client.post(PATH, json=payload()).json()["data"]["artifactHash"]
    with database.connect() as connection:
        connection.execute(f"UPDATE athena_rebound25_synthetic_artifacts SET {column} = ? WHERE artifact_hash = ?", (value, digest))
    assert client.get(PATH + "/" + digest).status_code == 503
    assert client.get(PATH).status_code == 503
    assert count(database) == 1

def test_rehashed_forged_prices_and_result_fail_server_regeneration(setup):
    database, service, _, client = setup
    data = client.post(PATH, json=payload()).json()["data"]
    request = deepcopy(data["request"])
    request["bars"][0]["high"] = 103.0
    result = service._calculate(request)
    digest = artifact_hash(owner_id=17, fixture_id=FIXTURE_ID, request=request,
                           result=result, created_at=data["createdAt"])
    with database.connect() as connection:
        connection.execute("UPDATE athena_rebound25_synthetic_artifacts SET artifact_hash = ?, request_json = ?, result_json = ?",
            (digest, canonical_json(request), canonical_json(result)))
    assert client.get(PATH + "/" + digest).status_code == 503
    assert client.get(PATH).status_code == 503

def test_rehashed_future_creation_time_is_rejected(setup):
    database, _, _, client = setup
    data = client.post(PATH, json=payload()).json()["data"]
    created = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    digest = artifact_hash(owner_id=17, fixture_id=FIXTURE_ID, request=data["request"],
                           result=data["result"], created_at=created)
    with database.connect() as connection:
        connection.execute("UPDATE athena_rebound25_synthetic_artifacts SET artifact_hash = ?, created_at = ?", (digest, created))
    assert client.get(PATH + "/" + digest).status_code == 503

def test_rehashed_creation_before_series_cutoff_is_rejected(setup):
    database, _, _, client = setup
    data = client.post(PATH, json=payload()).json()["data"]
    created = "2026-01-01T00:00:00+00:00"
    digest = artifact_hash(owner_id=17, fixture_id=FIXTURE_ID, request=data["request"],
                           result=data["result"], created_at=created)
    with database.connect() as connection:
        connection.execute("UPDATE athena_rebound25_synthetic_artifacts SET artifact_hash = ?, created_at = ?", (digest, created))
    assert client.get(PATH + "/" + digest).status_code == 503


def test_multiple_instances_serialize_replay_and_preserve_first_creation(setup):
    database, _, _, _ = setup
    barrier = threading.Barrier(6)
    def create(_):
        service = Rebound25ArtifactService(AthenaDatabase(database.database_path))
        parameters = Rebound25ParametersRequest.model_validate(PARAMETERS)
        barrier.wait(timeout=5)
        return service.create(owner_id=17, fixture_id=FIXTURE_ID, parameters=parameters)
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(create, range(6)))
    assert len({record["artifactHash"] for record in records}) == 1
    assert len({record["createdAt"] for record in records}) == 1
    assert count(database) == 1

def test_index_is_bounded_with_more_flag(setup):
    _, _, _, client = setup
    for target in (2.0, 3.0, 4.0):
        assert client.post(PATH, json={"fixtureId": FIXTURE_ID,
            "parameters": {**PARAMETERS, "takeProfitPct": target}}).status_code == 200
    data = client.get(PATH, params={"limit": 2}).json()["data"]
    assert data["returnedCount"] == 2 and data["hasMore"] is True
    assert len(data["items"]) == 2
    assert client.get(PATH, params={"limit": 51}).status_code == 422
    assert client.get(PATH, params={"limit": 0}).status_code == 422


def test_actual_application_registers_authenticated_artifact_router():
    from app.main import app as complete_app
    response = TestClient(complete_app).post(PATH, json=payload())
    assert response.status_code == 401

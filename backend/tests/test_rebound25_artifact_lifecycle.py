"""Research retention follows ACCOUNT_PRIVACY_LIFECYCLE, not mutable holdings."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, rebound25_artifacts as api
from app.api.rebound25_synthetic import Rebound25ParametersRequest
from app.database.athena_database import AthenaDatabase
from app.services.auth_service import AuthService
from app.services.database_backup_service import DatabaseBackupService
from app.services.rebound25_artifact_service import Rebound25ArtifactService

PARAMETERS = {"takeProfitPct": 2.0, "stopLossPct": 1.0, "maxHoldingSessions": 5,
              "commissionBps": 1.0, "spreadBps": 10.0, "slippageBps": 5.0,
              "orderUnits": 1.0, "minAverageVolume": 1.0,
              "maxVolumeParticipation": 0.01, "minRelativeVolume": 0.0}
PATH = "/api/v1/research/strategies/rebound25/artifacts"


def test_closed_owner_cannot_access_retained_artifact_and_other_owner_remains_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "live.db"))
    monkeypatch.setenv("ATHENA_AUTH_SECRET", "synthetic-lifecycle-secret-0123456789abcdef0123456789")
    accounts = AuthService()
    first = accounts.register(email="closed@example.invalid", password="SyntheticPassword123!")
    second = accounts.register(email="active@example.invalid", password="SyntheticPassword456!")
    first_id, second_id = int(first["id"]), int(second["id"])
    token = accounts.create_access_token(user_id=first_id, email=first["email"])
    other_token = accounts.create_access_token(user_id=second_id, email=second["email"])
    artifacts = Rebound25ArtifactService(AthenaDatabase())
    monkeypatch.setattr(api, "artifact_service", artifacts)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(auth.router)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"fixtureId": "synthetic-rebound25-demo-v1", "parameters": PARAMETERS}
    created = client.post(PATH, headers=headers, json=payload)
    assert created.status_code == 200, created.text
    original = created.json()["data"]
    assert accounts.close_account(user_id=first_id, current_password="SyntheticPassword123!")
    assert client.get(PATH, headers=headers).status_code == 401
    assert client.get(PATH + "/" + original["artifactHash"], headers=headers).status_code == 401
    assert client.post(PATH, headers=headers, json=payload).status_code == 401
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get(PATH + "/" + original["artifactHash"], headers=other_headers).status_code == 404
    assert client.get(PATH, headers=other_headers).json()["data"]["items"] == []
    # Internal verification retains immutable evidence, as the lifecycle contract requires.
    assert artifacts.get(owner_id=first_id, artifact_hash=original["artifactHash"]) == original


def test_dynamic_artifact_table_survives_verified_backup_restore_with_original_hash(tmp_path):
    database = AthenaDatabase(tmp_path / "live.db")
    artifacts = Rebound25ArtifactService(database)
    original = artifacts.create(owner_id=17, fixture_id="synthetic-rebound25-demo-v1",
                                parameters=Rebound25ParametersRequest.model_validate(PARAMETERS))
    backup = DatabaseBackupService(database)
    backup_path = tmp_path / "snapshots" / "artifact.db"
    metadata = backup.create_backup(backup_path)
    assert backup.verify_backup(backup_path) == metadata
    restored_path = tmp_path / "restored.db"
    assert backup.restore_backup(backup_path, restored_path) == metadata
    restored = Rebound25ArtifactService(AthenaDatabase(restored_path))
    assert restored.get(owner_id=17, artifact_hash=original["artifactHash"]) == original
    assert restored.list(owner_id=17)["returnedCount"] == 1

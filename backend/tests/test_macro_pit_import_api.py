from fastapi.testclient import TestClient

import app.api.macro as macro_api
from app.main import app


client = TestClient(app)


class FakeFred:
    configured = True

    def __init__(self) -> None:
        self.closed = False

    def get_observations(self, **kwargs):
        return {
            "observations": [
                {
                    "realtime_start": "2026-01-02",
                    "realtime_end": "2026-01-31",
                    "date": "2026-01-01",
                    "value": "4.25",
                }
            ]
        }

    def close(self) -> None:
        self.closed = True


class UnconfiguredFred(FakeFred):
    configured = False


def request_body() -> dict[str, object]:
    return {
        "seriesId": "DGS10",
        "observationStart": "2026-01-01",
        "observationEnd": "2026-01-01",
        "realtimeStart": "2026-01-02",
        "realtimeEnd": "2026-01-02",
        "asOf": "2026-01-03T00:00:00Z",
    }


def test_macro_pit_import_is_server_sourced_and_research_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setattr(macro_api, "FredAlfredService", FakeFred)
    response = client.post("/api/v1/macro/fred-alfred/pit-import", json=request_body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["seriesId"] == "DGS10"
    assert data["importedCount"] == 1
    assert len(data["observationKeys"][0]) == 64
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["source"] == "fred_alfred_server_side_only"


def test_macro_pit_import_rejects_client_secret_or_extra_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setattr(macro_api, "FredAlfredService", FakeFred)
    body = request_body()
    body["apiKey"] = "must-never-be-accepted"
    response = client.post("/api/v1/macro/fred-alfred/pit-import", json=body)
    assert response.status_code == 422


def test_macro_pit_import_returns_503_when_backend_secret_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(macro_api, "FredAlfredService", UnconfiguredFred)
    response = client.post("/api/v1/macro/fred-alfred/pit-import", json=request_body())
    assert response.status_code == 503
    assert "backend" in response.json()["detail"].lower()


def test_macro_pit_import_rejects_naive_as_of_before_connector(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "athena.db"))
    monkeypatch.setattr(macro_api, "FredAlfredService", FakeFred)
    body = request_body()
    body["asOf"] = "2026-01-03T00:00:00"
    response = client.post("/api/v1/macro/fred-alfred/pit-import", json=body)
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_source_catalog_reports_real_integration_states() -> None:
    response = client.get("/api/v1/sources")

    assert response.status_code == 200

    payload = response.json()
    sources = payload["data"]
    by_id = {source["id"]: source for source in sources}

    assert payload["summary"]["total"] == len(sources)
    assert by_id["yahoo_finance"]["status"] == "connected"
    assert by_id["nasdaq_trader"]["status"] == "connected"
    assert by_id["sec_edgar_xbrl"]["status"] == "ready_to_integrate"
    assert by_id["sec_13f"]["status"] == "ready_to_integrate"
    assert by_id["sec_form4"]["status"] == "ready_to_integrate"
    assert by_id["fred_alfred"]["requires_credentials"] is True
    assert by_id["google_trends"]["status"] == "restricted_access"
    assert by_id["analyst_consensus"]["status"] == "research_required"


def test_every_source_declares_traceability_metadata() -> None:
    response = client.get("/api/v1/sources")
    sources = response.json()["data"]

    required_keys = {
        "id",
        "name",
        "category",
        "purpose",
        "status",
        "official",
        "free_access",
        "requires_credentials",
        "notes",
    }

    assert sources
    for source in sources:
        assert required_keys.issubset(source)
        assert source["purpose"]

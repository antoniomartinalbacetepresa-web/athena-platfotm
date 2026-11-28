from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_allocation_authority_api_fails_closed_when_no_exact_authority_exists() -> None:
    response = client.post(
        "/api/v1/portfolio/allocation-authorities/resolve",
        json={
            "instrumentId": 999999991,
            "horizonDays": 30,
            "heldInstrumentIds": [],
            "asOf": "2026-09-05T12:00:00+00:00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "allocation_authorities_not_ready"
    assert data["allocationAuthoritiesReady"] is False
    assert data["reason"] == "action_authority_missing"
    assert data["callerSuppliedInternalFingerprintsRequired"] is False
    assert data["policySelectionPerformed"] is False
    assert data["economicContractInvented"] is False
    assert data["advisoryStatus"] == "no_advice"
    assert data["recommendationCandidateReady"] is False
    assert data["productionEligible"] is False
    assert data["allocationEligible"] is False
    assert data["automaticTrading"] is False
    assert "uncertaintyBoundActionCandidateFingerprint" not in data


def test_allocation_authority_api_rejects_naive_as_of() -> None:
    response = client.post(
        "/api/v1/portfolio/allocation-authorities/resolve",
        json={
            "instrumentId": 1,
            "horizonDays": 30,
            "heldInstrumentIds": [],
            "asOf": "2026-09-05T12:00:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_allocation_authority_api_rejects_duplicate_holdings() -> None:
    response = client.post(
        "/api/v1/portfolio/allocation-authorities/resolve",
        json={
            "instrumentId": 1,
            "horizonDays": 30,
            "heldInstrumentIds": [2, 2],
            "asOf": "2026-09-05T12:00:00+00:00",
        },
    )

    assert response.status_code == 400
    assert "duplicados" in response.json()["detail"]

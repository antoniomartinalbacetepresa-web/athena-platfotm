from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def payload(**overrides):
    body = {
        "portfolioId": "portfolio-nlv-api",
        "reportingCurrency": "EUR",
        "value": 1250.5,
        "observedAt": "2026-08-31T12:00:00Z",
        "availableAt": "2026-08-31T12:00:00Z",
        "phase": "regular",
        "source": "independent_broker_nlv",
        "sourceRef": "portfolio-nlv-api:2026-08-31:regular",
        "asOf": "2026-09-01T12:00:00Z",
    }
    body.update(overrides)
    return body


def test_nlv_api_persists_reads_and_preserves_research_contract():
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    data = body["data"]
    assert data["valuationScope"] == "total_net_liquidation_value_in_reporting_currency"
    assert data["value"] == 1250.5
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["cashInference"] == "forbidden"
    assert data["policy"]["liabilityInference"] == "forbidden"
    assert data["policy"]["unsettledInference"] == "forbidden"
    assert data["policy"]["fxInference"] == "forbidden"
    assert body["persistence"]["appendOnly"] is True
    assert body["persistence"]["tamperVerified"] is True
    assert len(data["snapshotKey"]) == 64

    read = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-nlv-snapshots/{data['snapshotKey']}"
    )
    assert read.status_code == 200
    assert read.json()["data"] == data
    assert read.json()["persistence"]["tamperVerified"] is True


def test_nlv_api_rejects_lookahead_naive_datetime_and_extra_fields():
    lookahead = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(
            sourceRef="portfolio-nlv-api:lookahead",
            availableAt="2026-09-02T12:00:00Z",
        ),
    )
    assert lookahead.status_code == 400

    naive = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(
            sourceRef="portfolio-nlv-api:naive",
            observedAt="2026-08-31T12:00:00",
        ),
    )
    assert naive.status_code == 400
    assert "zona horaria" in naive.json()["detail"]

    extra = payload(sourceRef="portfolio-nlv-api:extra")
    extra["cashBalance"] = 100.0
    response = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=extra,
    )
    assert response.status_code == 422


def test_nlv_api_rejects_provenance_conflict_and_invalid_phase():
    first = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(sourceRef="portfolio-nlv-api:conflict"),
    )
    assert first.status_code == 200
    conflicting = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(sourceRef="portfolio-nlv-api:conflict", value=999.0),
    )
    assert conflicting.status_code == 400
    assert "provenance" in conflicting.json()["detail"]

    invalid_phase = client.post(
        "/api/v1/recommendations/professional-research/portfolio-nlv-snapshots",
        json=payload(sourceRef="portfolio-nlv-api:phase", phase="estimated"),
    )
    assert invalid_phase.status_code == 400
    assert "phase" in invalid_phase.json()["detail"]

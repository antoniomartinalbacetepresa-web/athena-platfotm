from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.auth import current_account
from app.main import app
import test_recommendation_portfolio_time_weighted_return_api as twr_tests


client = TestClient(app)
OWNER_A = 101
OWNER_B = 202


def _account(owner_user_id: int):
    return lambda: {
        "id": owner_user_id,
        "email": f"owner-{owner_user_id}@example.com",
    }


def test_nlv_twr_and_attribution_fail_closed_across_authenticated_owners(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("ATHENA_DATABASE_PATH", str(tmp_path / "owner-bound-portfolio.db"))
    app.dependency_overrides[current_account] = _account(OWNER_A)

    twr_tests._ledger(monkeypatch, tmp_path)
    request_payload = twr_tests.payload(tag="owner-bound")
    created = client.post(
        "/api/v1/recommendations/professional-research/portfolio-time-weighted-return",
        json=request_payload,
    )
    assert created.status_code == 200, created.text
    measurement_key = created.json()["data"]["measurementKey"]
    first_snapshot_key = request_payload["boundaries"][0]["regularSnapshotKey"]

    own_snapshot = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-nlv-snapshots/{first_snapshot_key}"
    )
    own_measurement = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-time-weighted-return/{measurement_key}"
    )
    assert own_snapshot.status_code == 200
    assert own_measurement.status_code == 200

    app.dependency_overrides[current_account] = _account(OWNER_B)

    foreign_snapshot = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-nlv-snapshots/{first_snapshot_key}"
    )
    foreign_measurement = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-time-weighted-return/{measurement_key}"
    )
    assert foreign_snapshot.status_code == 404
    assert foreign_measurement.status_code == 404

    foreign_attribution = client.post(
        "/api/v1/recommendations/professional-research/portfolio-performance-attribution",
        json={
            "portfolioId": request_payload["portfolioId"],
            "benchmarkId": "SPY",
            "reportingCurrency": request_payload["reportingCurrency"],
            "measurementKey": measurement_key,
            "weightEvidenceKey": "b" * 64,
            "asOf": request_payload["asOf"],
            "periodStart": request_payload["periodStart"],
            "periodEnd": request_payload["periodEnd"],
            "constituents": [{"attributionKey": "c" * 64}],
        },
    )
    assert foreign_attribution.status_code == 400

    # Authentication itself is mandatory; knowing an opaque key is insufficient.
    app.dependency_overrides.pop(current_account, None)
    unauthenticated = client.get(
        f"/api/v1/recommendations/professional-research/portfolio-time-weighted-return/{measurement_key}"
    )
    assert unauthenticated.status_code == 401

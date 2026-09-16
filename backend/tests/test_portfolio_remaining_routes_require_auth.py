from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


_SHA = "a" * 64


def test_remaining_portfolio_evidence_routes_reject_anonymous_access() -> None:
    with TestClient(app) as client:
        event_response = client.get(
            "/api/v1/recommendations/professional-research/portfolio-event-ledger/external-cash-flows",
            params={
                "portfolioId": "portfolio-a",
                "reportingCurrency": "EUR",
                "periodStart": "2026-01-01T00:00:00+00:00",
                "periodEnd": "2026-01-31T00:00:00+00:00",
                "asOf": "2026-02-01T00:00:00+00:00",
            },
        )
        reconciliation_response = client.get(
            f"/api/v1/recommendations/professional-research/portfolio-state-reconciliation/{_SHA}"
        )
        weights_response = client.get(
            f"/api/v1/recommendations/professional-research/reconciled-portfolio-weights/{_SHA}"
        )

    for response in (
        event_response,
        reconciliation_response,
        weights_response,
    ):
        assert response.status_code == 401, response.text

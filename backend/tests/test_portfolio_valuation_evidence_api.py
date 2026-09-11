import pytest
from fastapi.testclient import TestClient

from app.api.auth import current_account
from app.main import app


FINGERPRINT = "a" * 64
RECORD_FINGERPRINT = "b" * 64
OWNER_ID = 1


@pytest.fixture(autouse=True)
def authenticated_account_override():
    app.dependency_overrides[current_account] = lambda: {"id": OWNER_ID, "email": "portfolio-test@example.invalid"}
    try:
        yield
    finally:
        app.dependency_overrides.pop(current_account, None)


def _artifact(*, production_eligible: bool = False) -> dict:
    return {"status": "portfolio_valuation_evidence_verified_non_advisory", "artifactVersion": "athena-portfolio-valuation-evidence-v1", "asOf": "2026-09-05T10:00:00+00:00", "baseCurrency": "EUR", "valuationScope": "invested_long_positions_only_cash_liabilities_unsettled_excluded", "cashIncluded": False, "liabilitiesIncluded": False, "positionCount": 1, "positions": [{"instrumentId": 7, "symbol": "AAPL", "positionValueInBaseCurrency": 1000.0}], "investedPositionsValueInBaseCurrency": 1000.0, "portfolioValuationEvidenceFingerprint": FINGERPRINT, "portfolioValuationEvidenceReady": True, "advisoryStatus": "no_advice", "productionEligible": production_eligible, "automaticTrading": False}


def _request() -> dict:
    return {"baseCurrency": "EUR", "asOf": "2026-09-05T10:00:00+00:00", "positions": [{"instrumentId": 7, "quantity": 5.0, "positionSourceProvider": "user_portfolio", "positionObservedAt": "2026-09-05T09:00:00+00:00", "positionRetrievedAt": "2026-09-05T09:00:01+00:00", "marketSourceProvider": "yahoo_chart"}]}


def test_portfolio_valuation_api_builds_validates_and_seals_for_authenticated_owner(monkeypatch) -> None:
    calls = []
    scoped = []
    artifact = _artifact()
    class FakeService:
        def build(self, *, positions, base_currency, as_of):
            calls.append((positions, base_currency, as_of.isoformat()))
            return artifact
        def validate_artifact(self, supplied):
            assert supplied is artifact
            return supplied
    class FakeRepository:
        def __init__(self, *, validator):
            assert isinstance(validator, FakeService)
    class FakeOwnerScopedRepository:
        def __init__(self, *, owner_user_id, repository):
            scoped.append((owner_user_id, repository))
        def seal(self, *, artifact):
            return {"artifact": artifact, "persisted_at": "2026-09-05T10:00:01+00:00", "record_fingerprint": RECORD_FINGERPRINT}
        def validate_record(self, record):
            return record
    monkeypatch.setattr("app.api.portfolio.RecommendationPortfolioValuationEvidenceService", FakeService)
    monkeypatch.setattr("app.api.portfolio.RecommendationPortfolioValuationEvidenceRepository", FakeRepository)
    monkeypatch.setattr("app.api.portfolio.OwnerScopedPortfolioValuationEvidenceRepository", FakeOwnerScopedRepository)
    response = TestClient(app).post("/api/v1/portfolio/valuation-evidence", json=_request())
    assert response.status_code == 200
    assert calls == [(_request()["positions"], "EUR", "2026-09-05T10:00:00+00:00")]
    assert scoped[0][0] == OWNER_ID
    assert isinstance(scoped[0][1], FakeRepository)
    body = response.json()
    assert body["data"]["portfolioValuationEvidenceFingerprint"] == FINGERPRINT
    assert body["data"]["advisoryStatus"] == "no_advice"
    assert body["data"]["productionEligible"] is False
    assert body["data"]["automaticTrading"] is False
    assert body["persistence"] == {"sealed": True, "persistedAt": "2026-09-05T10:00:01+00:00", "recordFingerprint": RECORD_FINGERPRINT}


def test_portfolio_valuation_api_rejects_naive_as_of(monkeypatch) -> None:
    class FakeService:
        def build(self, **kwargs):
            raise AssertionError("build must not run for a naive cutoff")
    monkeypatch.setattr("app.api.portfolio.RecommendationPortfolioValuationEvidenceService", FakeService)
    request = _request(); request["asOf"] = "2026-09-05T10:00:00"
    response = TestClient(app).post("/api/v1/portfolio/valuation-evidence", json=request)
    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


def test_portfolio_valuation_api_fails_closed_on_production_escape(monkeypatch) -> None:
    artifact = _artifact(production_eligible=True)
    class FakeService:
        def build(self, **kwargs): return artifact
        def validate_artifact(self, supplied): return supplied
    class FakeRepository:
        def __init__(self, *, validator): raise AssertionError("unsafe evidence must not reach persistence")
    monkeypatch.setattr("app.api.portfolio.RecommendationPortfolioValuationEvidenceService", FakeService)
    monkeypatch.setattr("app.api.portfolio.RecommendationPortfolioValuationEvidenceRepository", FakeRepository)
    response = TestClient(app).post("/api/v1/portfolio/valuation-evidence", json=_request())
    assert response.status_code in (409, 500)
    assert "producción" in response.json()["detail"] or "valoración PIT" in response.json()["detail"]


def test_portfolio_valuation_api_requires_positions_list() -> None:
    request = _request(); request["positions"] = "not-a-list"
    response = TestClient(app).post("/api/v1/portfolio/valuation-evidence", json=request)
    assert response.status_code == 400
    assert response.json()["detail"] == "positions debe ser una lista."

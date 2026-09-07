from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import recommendation_production as production_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.services.recommendation_production_read_service import (
    RecommendationProductionReadService,
)


FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64
FP_D = "d" * 64


class FakeRecommendationRepository:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records

    def initialize(self) -> None:
        return None

    def get(self, *, authorization_id: str):
        return self.records.get(authorization_id)


class FakeAllocationRepository:
    def __init__(self, records: dict[str, dict[str, object]]) -> None:
        self.records = records

    def initialize(self) -> None:
        return None

    def get(self, *, authorization_id: str):
        return self.records.get(authorization_id)


def _recommendation(*, authorized_at: str = "2026-09-01T12:00:00+00:00") -> dict[str, object]:
    authorization = {
        "status": "production_recommendation_authorized",
        "advisoryStatus": "production_recommendation",
        "recommendationCandidateReady": True,
        "productionEligible": True,
        "allocationEligible": False,
        "automaticTrading": False,
        "authorizationFingerprint": FP_A,
        # v1 recommendation authorizations persist this canonical DB id as text.
        "instrumentId": "7",
        "symbol": "AAPL",
        "action": "buy",
        "economicContractFingerprint": FP_B,
        "asOf": "2026-08-31T20:00:00+00:00",
        "authorizedAt": authorized_at,
    }
    return {"authorization": authorization}


def _allocation(*, recommendation_fp: str = FP_A, instrument_id: int = 7) -> dict[str, object]:
    authorization = {
        "status": "production_allocation_authorized",
        "advisoryStatus": "production_allocation",
        "productionEligible": True,
        "allocationEligible": True,
        "executionEligible": False,
        "orderRoutingEligible": False,
        "automaticTrading": False,
        "authorizationFingerprint": FP_C,
        "recommendationAuthorizationFingerprint": recommendation_fp,
        # Allocation authorization uses the canonical integer DB identity.
        "instrumentId": instrument_id,
        "symbol": "AAPL",
        "action": "buy",
        "economicContractFingerprint": FP_B,
        "asOf": "2026-08-31T20:00:00+00:00",
        "authorizedAt": "2026-09-01T12:30:00+00:00",
    }
    return {"authorization": authorization}


def _service(tmp_path, *, recommendation=None, allocation=None):
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE athena_recommendation_production_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                authorization_id TEXT NOT NULL,
                authorized_at TEXT NOT NULL
            );
            CREATE TABLE athena_recommendation_production_allocation_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                authorization_id TEXT NOT NULL,
                recommendation_authorization_fingerprint TEXT NOT NULL,
                authorized_at TEXT NOT NULL
            );
            """
        )
        if recommendation is not None:
            connection.execute(
                "INSERT INTO athena_recommendation_production_authorizations "
                "(authorization_id, authorized_at) VALUES (?, ?)",
                ("rec-1", recommendation["authorization"]["authorizedAt"]),
            )
        if allocation is not None:
            connection.execute(
                "INSERT INTO athena_recommendation_production_allocation_authorizations "
                "(authorization_id, recommendation_authorization_fingerprint, authorized_at) "
                "VALUES (?, ?, ?)",
                (
                    "alloc-1",
                    allocation["authorization"]["recommendationAuthorizationFingerprint"],
                    allocation["authorization"]["authorizedAt"],
                ),
            )
    return RecommendationProductionReadService(
        database=database,
        recommendation_repository=FakeRecommendationRepository(
            {"rec-1": recommendation} if recommendation is not None else {}
        ),
        allocation_repository=FakeAllocationRepository(
            {"alloc-1": allocation} if allocation is not None else {}
        ),
    )


def test_returns_only_authorizations_known_at_cutoff(tmp_path) -> None:
    service = _service(tmp_path, recommendation=_recommendation(), allocation=_allocation())
    before = service.resolve_latest(
        as_of=datetime(2026, 9, 1, 11, 59, tzinfo=timezone.utc),
        symbol="AAPL",
    )
    assert before["recommendation"] is None
    assert before["allocation"] is None
    assert before["productionRecommendationAvailable"] is False

    after = service.resolve_latest(
        as_of=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        symbol="aapl",
    )
    assert after["recommendation"]["authorizationFingerprint"] == FP_A
    assert after["allocation"]["authorizationFingerprint"] == FP_C
    assert after["automaticTrading"] is False
    assert after["readOnly"] is True


def test_canonicalizes_v1_text_recommendation_id_against_integer_allocation(tmp_path) -> None:
    service = _service(tmp_path, recommendation=_recommendation(), allocation=_allocation())
    result = service.resolve_latest(
        as_of=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        instrument_id=7,
    )
    assert result["recommendation"] is not None
    assert result["allocation"] is not None
    assert result["productionAllocationAvailable"] is True


def test_rejects_allocation_with_different_instrument_identity(tmp_path) -> None:
    service = _service(
        tmp_path,
        recommendation=_recommendation(),
        allocation=_allocation(instrument_id=8),
    )
    with pytest.raises(ValueError, match="instrumentId"):
        service.resolve_latest(
            as_of=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            symbol="AAPL",
        )


def test_rejects_allocation_recomposed_from_another_recommendation(tmp_path) -> None:
    service = _service(
        tmp_path,
        recommendation=_recommendation(),
        allocation=_allocation(recommendation_fp=FP_D),
    )
    result = service.resolve_latest(
        as_of=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        symbol="AAPL",
    )
    assert result["recommendation"] is not None
    assert result["allocation"] is None
    assert result["productionAllocationAvailable"] is False


def test_requires_instrument_scope_and_timezone(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="symbol o instrument_id"):
        service.resolve_latest(as_of=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="zona horaria"):
        service.resolve_latest(as_of=datetime(2026, 9, 1, 12, 0), symbol="AAPL")


def test_get_endpoint_is_read_only_and_fails_closed(monkeypatch) -> None:
    class FakeService:
        def resolve_latest(self, **kwargs):
            return {
                "asOf": "2026-09-01T13:00:00+00:00",
                "symbol": "AAPL",
                "instrumentId": None,
                "recommendation": None,
                "allocation": None,
                "productionRecommendationAvailable": False,
                "productionAllocationAvailable": False,
                "automaticTrading": False,
                "readOnly": True,
            }

    monkeypatch.setattr(production_api, "production_read_service", FakeService())
    response = TestClient(app).get(
        "/api/v1/recommendations/production/latest",
        params={"symbol": "AAPL", "as_of": "2026-09-01T13:00:00+00:00"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["productionRecommendationAvailable"] is False
    assert TestClient(app).post("/api/v1/recommendations/production/latest").status_code == 405

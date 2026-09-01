from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


@dataclass(frozen=True)
class _Gate:
    candidate_ready: bool = False
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, object]:
        return {
            "status": "core_evidence_ready",
            "symbol": "AAPL",
            "asOf": "2026-09-01T20:30:00+00:00",
            "instrumentId": 1,
            "coreEvidenceReady": True,
            "marketEvidenceReady": True,
            "fundamentalEvidenceReady": True,
            "identityConsistent": True,
            "provenanceContractReady": True,
            "valuationReady": False,
            "calibrationReady": False,
            "recommendationCandidateReady": self.candidate_ready,
            "blockers": ["valuation_not_ready", "calibration_not_validated"],
            "productionEligible": self.production_eligible,
            "reason": "Diagnóstico bloqueado antes de valoración y calibración.",
        }


class _GateService:
    def __init__(
        self,
        *,
        candidate_ready: bool = False,
        production_eligible: bool = False,
    ) -> None:
        self.candidate_ready = candidate_ready
        self.production_eligible = production_eligible
        self.calls: list[dict[str, object]] = []

    def evaluate(self, *, symbol: str, as_of: datetime) -> _Gate:
        self.calls.append({"symbol": symbol, "as_of": as_of})
        return _Gate(
            candidate_ready=self.candidate_ready,
            production_eligible=self.production_eligible,
        )


def test_evidence_gate_endpoint_exposes_blockers_without_advice(monkeypatch) -> None:
    fake = _GateService()
    monkeypatch.setattr(recommendations, "evidence_gate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/evidence-gate",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00+00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["advisoryStatus"] == "diagnostic_only"
    assert body["data"]["coreEvidenceReady"] is True
    assert body["data"]["recommendationCandidateReady"] is False
    assert body["data"]["productionEligible"] is False
    assert body["data"]["blockers"] == [
        "valuation_not_ready",
        "calibration_not_validated",
    ]
    assert len(fake.calls) == 1
    assert fake.calls[0]["symbol"] == "AAPL"
    as_of = fake.calls[0]["as_of"]
    assert isinstance(as_of, datetime)
    assert as_of.utcoffset() is not None


def test_evidence_gate_endpoint_rejects_naive_as_of_before_service(monkeypatch) -> None:
    fake = _GateService()
    monkeypatch.setattr(recommendations, "evidence_gate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/evidence-gate",
        params={
            "symbol": "AAPL",
            "as_of": "2026-09-01T20:30:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
    assert fake.calls == []


def test_evidence_gate_endpoint_blocks_accidental_candidate_enablement(
    monkeypatch,
) -> None:
    fake = _GateService(candidate_ready=True)
    monkeypatch.setattr(recommendations, "evidence_gate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/evidence-gate",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 500
    assert "habilitar una recomendación" in response.json()["detail"]


def test_evidence_gate_endpoint_blocks_accidental_production_eligibility(
    monkeypatch,
) -> None:
    fake = _GateService(production_eligible=True)
    monkeypatch.setattr(recommendations, "evidence_gate_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/diagnostics/evidence-gate",
        params={"symbol": "AAPL"},
    )

    assert response.status_code == 500
    assert "política de seguridad" in response.json()["detail"]

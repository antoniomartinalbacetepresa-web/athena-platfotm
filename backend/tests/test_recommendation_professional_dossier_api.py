from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api import recommendation_production


class FakeProfessionalDossierService:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


def _safe_payload():
    return {
        "status": "professional_dossier_no_production_recommendation",
        "asOf": "2026-09-01T12:00:00+00:00",
        "symbol": "AAPL",
        "instrumentId": 7,
        "decision": None,
        "evidence": {
            "productionRecommendationAuthorized": False,
            "productionAllocationAuthorized": False,
        },
        "professionalModules": {
            "expectationsGap": {
                "status": "not_yet_evidenced",
                "productionEligible": False,
                "reason": "No existe todavía evidencia PIT sellada.",
            },
            "reverseValuation": {
                "status": "not_yet_evidenced",
                "productionEligible": False,
                "reason": "No existe todavía evidencia PIT sellada.",
            },
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "allocationEligible": False,
        "executionEligible": False,
        "orderRoutingEligible": False,
        "automaticTrading": False,
        "readOnly": True,
    }


def test_professional_dossier_endpoint_preserves_pit_cutoff_and_safe_contract(monkeypatch) -> None:
    service = FakeProfessionalDossierService(payload=_safe_payload())
    monkeypatch.setattr(recommendation_production, "professional_dossier_service", service)
    as_of = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)

    result = recommendation_production.get_professional_dossier(
        symbol="AAPL",
        instrument_id=7,
        as_of=as_of,
    )

    assert result["data"]["advisoryStatus"] == "no_advice"
    assert result["data"]["automaticTrading"] is False
    assert result["data"]["readOnly"] is True
    assert service.calls == [{"as_of": as_of, "symbol": "AAPL", "instrument_id": 7}]


def test_professional_dossier_endpoint_fails_closed_on_unsafe_projection(monkeypatch) -> None:
    payload = _safe_payload()
    payload["automaticTrading"] = True
    service = FakeProfessionalDossierService(payload=payload)
    monkeypatch.setattr(recommendation_production, "professional_dossier_service", service)

    with pytest.raises(HTTPException) as exc_info:
        recommendation_production.get_professional_dossier(
            symbol="AAPL",
            instrument_id=7,
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
        )

    assert exc_info.value.status_code == 500
    assert "seguridad" in str(exc_info.value.detail)


def test_professional_dossier_endpoint_rejects_unsealed_module_promotion(monkeypatch) -> None:
    payload = _safe_payload()
    payload["professionalModules"]["expectationsGap"]["productionEligible"] = True
    service = FakeProfessionalDossierService(payload=payload)
    monkeypatch.setattr(recommendation_production, "professional_dossier_service", service)

    with pytest.raises(HTTPException) as exc_info:
        recommendation_production.get_professional_dossier(
            symbol=None,
            instrument_id=7,
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
        )

    assert exc_info.value.status_code == 500
    assert "no evidenciado" in str(exc_info.value.detail)


def test_professional_dossier_endpoint_maps_validation_failure_to_400(monkeypatch) -> None:
    service = FakeProfessionalDossierService(error=ValueError("evidencia productiva inválida"))
    monkeypatch.setattr(recommendation_production, "professional_dossier_service", service)

    with pytest.raises(HTTPException) as exc_info:
        recommendation_production.get_professional_dossier(
            symbol="AAPL",
            instrument_id=None,
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "evidencia productiva inválida"


@pytest.mark.parametrize("route", ["dossier", "latest"])
def test_production_read_routes_reject_future_pit_before_service_call(monkeypatch, route) -> None:
    class SpyReadService:
        calls = 0

        def resolve_latest(self, **kwargs):
            self.calls += 1
            raise AssertionError("future PIT must not access production state")

    dossier = FakeProfessionalDossierService(payload=_safe_payload())
    production = SpyReadService()
    monkeypatch.setattr(recommendation_production, "professional_dossier_service", dossier)
    monkeypatch.setattr(recommendation_production, "production_read_service", production)
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    with pytest.raises(HTTPException) as exc_info:
        if route == "dossier":
            recommendation_production.get_professional_dossier(
                symbol="AAPL", instrument_id=7, as_of=future
            )
        else:
            recommendation_production.get_latest_production_state(
                symbol="AAPL", instrument_id=7, as_of=future
            )
    assert exc_info.value.status_code == 400
    assert "futuro" in str(exc_info.value.detail)
    assert dossier.calls == []
    assert production.calls == 0

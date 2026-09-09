from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk_sealed_value as sealed_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"
VALUE_KEY = "7" * 64
MARKET_KEY = "8" * 64


class FakeValueRepository:
    def __init__(self, *, instrument_id=1, as_of=AS_OF, value=0.35, key=VALUE_KEY, missing=False):
        self.instrument_id = instrument_id
        self.as_of = as_of
        self.value = value
        self.key = key
        self.missing = missing
        self.calls = []

    def get(self, *, factor_exposure_key):
        self.calls.append(factor_exposure_key)
        if self.missing:
            return None
        return {
            "artifact": {
                "module": "pit_value_factor_exposure",
                "factorExposureKey": self.key,
                "instrumentId": self.instrument_id,
                "asOf": self.as_of,
                "availableAt": self.as_of,
                "factors": {"value": self.value},
            }
        }


def request_body(*, with_value=True):
    position = {
        "instrumentId": 1,
        "symbol": "AAA",
        "marketExposureKey": MARKET_KEY,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:1",
        "factors": {},
    }
    if with_value:
        position["valueExposureKey"] = VALUE_KEY
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "a" * 64,
        "portfolioValuationEvidenceFingerprint": "b" * 64,
        "asOf": AS_OF,
        "positions": [position],
    }


def legacy_response(*, include_value=True, value=0.35):
    factors = {"market": 1.0}
    if include_value:
        factors["value"] = value
    return {
        "data": {
            "positions": [
                {
                    "instrumentId": 1,
                    "symbol": "AAA",
                    "weight": 1.0,
                    "factors": factors,
                }
            ],
            "stateIntegrity": {
                "reconciliationKey": "a" * 64,
                "portfolioStateKey": "c" * 64,
                "portfolioValuationEvidenceFingerprint": "b" * 64,
                "weightEvidenceKey": "d" * 64,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }
    }


def test_factor_risk_gate_injects_only_persisted_value_and_binds_output(monkeypatch) -> None:
    repository = FakeValueRepository()
    captured = []

    def fake_legacy(request):
        captured.append(request)
        assert request.positions[0].factors["value"] == 0.35
        assert request.positions[0].source.endswith("sealed_value_factor")
        assert f"value:{VALUE_KEY}" in request.positions[0].sourceRef
        return legacy_response()

    monkeypatch.setattr(sealed_api, "_value_repository", repository)
    monkeypatch.setattr(sealed_api.legacy_factor_risk, "post_factor_risk", fake_legacy)

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["positions"][0]["factors"]["value"] == 0.35
    assert data["stateIntegrity"]["valueExposureKeys"] == {"1": VALUE_KEY}
    assert data["stateIntegrity"]["callerSuppliedValueAccepted"] is False
    assert data["stateIntegrity"]["valueFactorDerivation"] == (
        "sealed_issuer_deduplicated_pit_book_to_market_or_explicitly_missing"
    )
    assert repository.calls == [VALUE_KEY]
    assert len(captured) == 1


def test_factor_risk_gate_rejects_free_value_before_legacy(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: called.append(request),
    )
    body = request_body(with_value=False)
    body["positions"][0]["factors"] = {"value": 0.9}

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=body,
    )

    assert response.status_code == 400
    assert "value" in response.json()["detail"]
    assert called == []


def test_factor_risk_gate_rejects_value_key_from_other_instrument_or_asof(monkeypatch) -> None:
    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(),
    )
    monkeypatch.setattr(sealed_api, "_value_repository", FakeValueRepository(instrument_id=2))
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(),
    )
    assert response.status_code == 400
    assert "otro instrumento" in response.json()["detail"]

    monkeypatch.setattr(
        sealed_api,
        "_value_repository",
        FakeValueRepository(as_of="2025-12-31T00:00:00+00:00"),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(),
    )
    assert response.status_code == 400
    assert "otro asOf" in response.json()["detail"]


def test_factor_risk_gate_rejects_missing_value_artifact(monkeypatch) -> None:
    monkeypatch.setattr(sealed_api, "_value_repository", FakeValueRepository(missing=True))
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(),
    )
    assert response.status_code == 400
    assert "No existe value" in response.json()["detail"]


def test_factor_risk_gate_fails_closed_if_legacy_changes_or_invents_value(monkeypatch) -> None:
    monkeypatch.setattr(sealed_api, "_value_repository", FakeValueRepository())
    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(value=0.99),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(),
    )
    assert response.status_code == 500
    assert "alteró value" in response.json()["detail"]

    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(include_value=True),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False),
    )
    assert response.status_code == 500
    assert "inventó value" in response.json()["detail"]


def test_factor_risk_public_route_is_single_registered_boundary() -> None:
    assert "/api/v1/recommendations/professional-research/factor-risk" in app.openapi()["paths"]
    paths = [
        route.path
        for route in app.routes
        if hasattr(route, "path")
        and route.path == "/api/v1/recommendations/professional-research/factor-risk"
    ]
    assert len(paths) == 1

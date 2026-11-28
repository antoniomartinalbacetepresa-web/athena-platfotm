from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk_sealed_value as sealed_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"
VALUE_KEY = "7" * 64
QUALITY_KEY = "6" * 64
MARKET_KEY = "8" * 64


class FakeFactorRepository:
    def __init__(
        self,
        *,
        factor: str,
        module: str,
        key: str,
        instrument_id: int = 1,
        as_of: str = AS_OF,
        value: float = 0.35,
        missing: bool = False,
        production_eligible: bool = False,
    ) -> None:
        self.factor = factor
        self.module = module
        self.key = key
        self.instrument_id = instrument_id
        self.as_of = as_of
        self.value = value
        self.missing = missing
        self.production_eligible = production_eligible
        self.calls: list[str] = []

    def get(self, *, factor_exposure_key: str):
        self.calls.append(factor_exposure_key)
        if self.missing:
            return None
        return {
            "artifact": {
                "module": self.module,
                "factorExposureKey": self.key,
                "instrumentId": self.instrument_id,
                "asOf": self.as_of,
                "availableAt": AVAILABLE_AT,
                "factors": {self.factor: self.value},
                "advisoryStatus": "no_advice",
                "productionEligible": self.production_eligible,
                "isWeightingReady": False,
            }
        }


def value_repository(**kwargs):
    return FakeFactorRepository(
        factor="value", module="pit_value_factor_exposure", key=VALUE_KEY, value=0.35, **kwargs
    )


def quality_repository(**kwargs):
    return FakeFactorRepository(
        factor="quality", module="pit_quality_factor_exposure", key=QUALITY_KEY, value=0.25, **kwargs
    )


def request_body(*, with_value: bool = True, with_quality: bool = False):
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
    if with_quality:
        position["qualityExposureKey"] = QUALITY_KEY
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "a" * 64,
        "portfolioValuationEvidenceFingerprint": "b" * 64,
        "asOf": AS_OF,
        "positions": [position],
    }


def legacy_response(*, include_value: bool = True, value: float = 0.35, include_quality: bool = False, quality: float = 0.25):
    factors = {"market": 1.0}
    if include_value:
        factors["value"] = value
    if include_quality:
        factors["quality"] = quality
    return {
        "data": {
            "positions": [{"instrumentId": 1, "symbol": "AAA", "weight": 1.0, "factors": factors}],
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


def test_factor_risk_gate_injects_sealed_value_and_quality_and_binds_output(monkeypatch) -> None:
    values = value_repository()
    qualities = quality_repository()
    captured = []

    def fake_legacy(request):
        captured.append(request)
        position = request.positions[0]
        assert position.factors["value"] == 0.35
        assert position.factors["quality"] == 0.25
        assert "sealed_value_factor" in position.source
        assert "sealed_quality_factor" in position.source
        return legacy_response(include_quality=True)

    monkeypatch.setattr(sealed_api, "_value_repository", values)
    monkeypatch.setattr(sealed_api, "_quality_repository", qualities)
    monkeypatch.setattr(sealed_api.legacy_factor_risk, "post_factor_risk", fake_legacy)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_quality=True),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["positions"][0]["factors"]["value"] == 0.35
    assert data["positions"][0]["factors"]["quality"] == 0.25
    state = data["stateIntegrity"]
    assert state["valueExposureKeys"] == {"1": VALUE_KEY}
    assert state["qualityExposureKeys"] == {"1": QUALITY_KEY}
    assert state["callerSuppliedValueAccepted"] is False
    assert state["callerSuppliedQualityAccepted"] is False
    assert state["callerSuppliedNumericFactorAccepted"] is False
    assert state["qualityFactorDerivation"] == "sealed_issuer_deduplicated_pit_annual_operating_margin_or_explicitly_missing"
    assert len(captured) == 1


def test_factor_risk_gate_rejects_free_value_or_quality_before_legacy(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(sealed_api.legacy_factor_risk, "post_factor_risk", lambda request: called.append(request))
    for factor in ("value", "quality"):
        body = request_body(with_value=False)
        body["positions"][0]["factors"] = {factor: 0.9}
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-risk", json=body
        )
        assert response.status_code == 400
    assert called == []


def test_factor_risk_gate_rejects_factor_key_from_other_instrument_or_asof(monkeypatch) -> None:
    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(include_quality=True),
    )
    monkeypatch.setattr(sealed_api, "_quality_repository", quality_repository(instrument_id=2))
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False, with_quality=True),
    )
    assert response.status_code == 400
    assert "otro instrumento" in response.json()["detail"]

    monkeypatch.setattr(
        sealed_api,
        "_quality_repository",
        quality_repository(as_of="2025-12-31T00:00:00+00:00"),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False, with_quality=True),
    )
    assert response.status_code == 400
    assert "otro asOf" in response.json()["detail"]


def test_factor_risk_gate_rejects_missing_or_unsafe_persisted_factor(monkeypatch) -> None:
    monkeypatch.setattr(sealed_api, "_quality_repository", quality_repository(missing=True))
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False, with_quality=True),
    )
    assert response.status_code == 400
    assert "No existe quality" in response.json()["detail"]

    monkeypatch.setattr(
        sealed_api,
        "_quality_repository",
        quality_repository(production_eligible=True),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False, with_quality=True),
    )
    assert response.status_code == 500
    assert "research-only" in response.json()["detail"]


def test_factor_risk_gate_fails_closed_if_legacy_changes_or_invents_fundamentals(monkeypatch) -> None:
    monkeypatch.setattr(sealed_api, "_value_repository", value_repository())
    monkeypatch.setattr(sealed_api, "_quality_repository", quality_repository())
    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(value=0.99),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk", json=request_body()
    )
    assert response.status_code == 500
    assert "alteró value" in response.json()["detail"]

    monkeypatch.setattr(
        sealed_api.legacy_factor_risk,
        "post_factor_risk",
        lambda request: legacy_response(include_value=False, include_quality=True, quality=0.99),
    )
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk",
        json=request_body(with_value=False, with_quality=True),
    )
    assert response.status_code == 500
    assert "alteró quality" in response.json()["detail"]

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


def test_factor_risk_public_route_is_registered_in_openapi_contract() -> None:
    path = app.openapi()["paths"]["/api/v1/recommendations/professional-research/factor-risk"]
    assert set(path) == {"post"}
    assert path["post"]["operationId"].startswith("post_factor_risk_with_sealed_value_")

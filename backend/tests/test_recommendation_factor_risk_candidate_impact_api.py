from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk_candidate_impact as candidate_api
from app.api import recommendation_factor_risk_sealed_value as sealed_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"
QUALITY_BASE_KEY = "e" * 64
QUALITY_CANDIDATE_KEY = "f" * 64
VALUE_BASE_KEY = "9" * 64
VALUE_CANDIDATE_KEY = "8" * 64


@dataclass(frozen=True)
class _Result:
    payload: dict[str, object]

    def to_api_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _Service:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> _Result:
        self.calls.append(kwargs)
        return _Result(self.payload)


class _ReconciliationRepository:
    def require_reconciled(self, **kwargs: object) -> dict[str, object]:
        return {"portfolio_state_key": "a" * 64, "artifact": {"reconciled": True}}


class _ValuationRepository:
    def get(self, **kwargs: object) -> dict[str, object]:
        return {"artifact": {"portfolioValuationEvidenceFingerprint": "b" * 64}}

    def validate_record(self, record: dict[str, object]) -> dict[str, object]:
        return record


class _WeightService:
    def build(self, **kwargs: object) -> dict[str, object]:
        return {
            "portfolioId": "portfolio-1",
            "reportingCurrency": "USD",
            "asOf": AS_OF,
            "reconciliationKey": "c" * 64,
            "portfolioStateKey": "a" * 64,
            "portfolioValuationEvidenceFingerprint": "b" * 64,
            "weightEvidenceKey": "d" * 64,
            "cashWeight": 0.4,
            "positions": [{"instrumentId": 1, "symbol": "AAA", "weight": 0.6}],
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


class _FactorRepository:
    def __init__(self, *, factor: str, module: str, records: dict[str, tuple[int, float]]) -> None:
        self.factor = factor
        self.module = module
        self.records = records

    def get(self, *, factor_exposure_key: str):
        item = self.records.get(factor_exposure_key)
        if item is None:
            return None
        instrument_id, value = item
        return {
            "artifact": {
                "module": self.module,
                "factorExposureKey": factor_exposure_key,
                "instrumentId": instrument_id,
                "asOf": AS_OF,
                "availableAt": AVAILABLE_AT,
                "factors": {self.factor: value},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
            }
        }


def _install_evidence(monkeypatch) -> None:
    monkeypatch.setattr(candidate_api, "_reconciliation_repository", _ReconciliationRepository())
    monkeypatch.setattr(candidate_api, "_valuation_repository", _ValuationRepository())
    monkeypatch.setattr(candidate_api, "_weight_service", _WeightService())
    monkeypatch.setattr(
        sealed_api,
        "_quality_repository",
        _FactorRepository(
            factor="quality",
            module="pit_quality_factor_exposure",
            records={QUALITY_BASE_KEY: (1, 0.2), QUALITY_CANDIDATE_KEY: (2, 0.2)},
        ),
    )
    monkeypatch.setattr(
        sealed_api,
        "_value_repository",
        _FactorRepository(
            factor="value",
            module="pit_value_factor_exposure",
            records={VALUE_BASE_KEY: (1, 0.4), VALUE_CANDIDATE_KEY: (2, -0.1)},
        ),
    )


def _candidate(*, with_value: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "instrumentId": 2,
        "symbol": "BBB",
        "weight": 0.2,
        "qualityExposureKey": QUALITY_CANDIDATE_KEY,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:2:2025-12-31",
        "factors": {},
    }
    if with_value:
        result["valueExposureKey"] = VALUE_CANDIDATE_KEY
    return result


def _policy(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "funding": "candidate_weight_is_explicit_caller_input_and_must_be_funded_from_existing_cash",
        "comparison": "only_factors_fully_covered_before_and_after_are_compared",
        "missingFactorCoverage": "coverage_loss_is_reported_never_imputed_as_zero",
        "covariance": "not_estimated_no_marginal_variance_or_risk_contribution_claim",
        "fx": "usd_fx_remains_explicit_and_is_never_silently_hedged",
        "thresholds": "not_calibrated",
        "interpretation": "candidate_factor_exposure_impact_not_position_sizing_or_trade_advice",
        "automaticTrading": False,
        "automaticProductionPromotion": False,
    }
    payload.update(overrides)
    return payload


def _payload(*, include_value: bool = False, **overrides: object) -> dict[str, object]:
    candidate_factors = {"quality": 0.2}
    comparable = ["quality"]
    before = {"quality": 0.12}
    after = {"quality": 0.16}
    deltas = {"quality": 0.04}
    if include_value:
        candidate_factors["value"] = -0.1
        comparable.append("value")
        before["value"] = 0.24
        after["value"] = 0.22
        deltas["value"] = -0.02
    candidate = {
        "instrumentId": 2,
        "symbol": "BBB",
        "weight": 0.2,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store+sealed_quality_factor" + ("+sealed_value_factor" if include_value else ""),
        "sourceRef": "factor:2:2025-12-31",
        "factors": candidate_factors,
    }
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "asOf": AS_OF,
        "candidate": candidate,
        "baselineInvestedWeight": 0.6,
        "baselineCashWeight": 0.4,
        "postInvestedWeight": 0.8,
        "postCashWeight": 0.2,
        "comparableFactors": comparable,
        "coverageLostFactors": [],
        "baselineWeightedExposures": before,
        "postWeightedExposures": after,
        "factorExposureDeltas": deltas,
        "baselineComparableGrossExposure": sum(abs(v) for v in before.values()),
        "postComparableGrossExposure": sum(abs(v) for v in after.values()),
        "comparableGrossExposureDelta": sum(abs(v) for v in after.values()) - sum(abs(v) for v in before.values()),
        "baselineComparableMaxAbsExposure": max(abs(v) for v in before.values()),
        "postComparableMaxAbsExposure": max(abs(v) for v in after.values()),
        "comparableMaxAbsExposureDelta": max(abs(v) for v in after.values()) - max(abs(v) for v in before.values()),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": _policy(),
    }
    payload.update(overrides)
    return payload


def _request(*, with_value: bool = False) -> dict[str, object]:
    baseline: dict[str, object] = {
        "instrumentId": 1,
        "symbol": "AAA",
        "qualityExposureKey": QUALITY_BASE_KEY,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:1:2025-12-31",
        "factors": {},
    }
    if with_value:
        baseline["valueExposureKey"] = VALUE_BASE_KEY
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "c" * 64,
        "portfolioValuationEvidenceFingerprint": "b" * 64,
        "asOf": AS_OF,
        "positions": [baseline],
        "candidate": _candidate(with_value=with_value),
    }


def test_candidate_impact_consumes_sealed_quality_with_empty_caller_factors(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=_request(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["candidate"]["factors"]["quality"] == 0.2
    state = data["stateIntegrity"]
    assert state["baselineQualityExposureKeys"] == {"1": QUALITY_BASE_KEY}
    assert state["candidateQualityExposureKey"] == QUALITY_CANDIDATE_KEY
    assert state["callerSuppliedQualityAccepted"] is False
    assert state["callerSuppliedNumericFactorAccepted"] is False
    assert len(service.calls) == 1
    evaluated_baseline = service.calls[0]["positions"][0]  # type: ignore[index]
    evaluated_candidate = service.calls[0]["candidate"]
    assert evaluated_baseline.factors == {"quality": 0.2}
    assert evaluated_candidate.factors == {"quality": 0.2}


def test_candidate_impact_can_compare_sealed_value_and_quality(monkeypatch) -> None:
    service = _Service(_payload(include_value=True))
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=_request(with_value=True),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data["comparableFactors"]) == {"value", "quality"}
    assert data["stateIntegrity"]["baselineValueExposureKeys"] == {"1": VALUE_BASE_KEY}
    assert data["stateIntegrity"]["candidateValueExposureKey"] == VALUE_CANDIDATE_KEY


def test_candidate_impact_rejects_free_value_or_quality_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    for factor in ("value", "quality"):
        body = _request()
        body["positions"][0]["factors"] = {factor: 0.5}  # type: ignore[index]
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
            json=body,
        )
        assert response.status_code == 400
    assert service.calls == []


def test_candidate_impact_rejects_other_sealed_factors_from_caller(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    for factor in ("market", "momentum", "low_volatility", "size", "rates", "usd_fx"):
        body = _request()
        body["candidate"]["factors"] = {factor: 0.5}  # type: ignore[index]
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
            json=body,
        )
        assert response.status_code == 400
    assert service.calls == []


def test_candidate_impact_rejects_quality_key_bound_to_other_instrument(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["candidate"]["qualityExposureKey"] = QUALITY_BASE_KEY  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "otro instrumento" in response.json()["detail"]
    assert service.calls == []


def test_candidate_impact_fails_closed_if_output_alters_sealed_quality(monkeypatch) -> None:
    payload = _payload()
    payload["candidate"] = {**payload["candidate"], "factors": {"quality": 0.9}}  # type: ignore[arg-type]
    service = _Service(payload)
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=_request(),
    )
    assert response.status_code == 500
    assert "alteró quality" in response.json()["detail"]


def test_candidate_impact_api_rejects_baseline_caller_weight_and_naive_times(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["positions"][0]["weight"] = 0.6  # type: ignore[index]
    assert client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact", json=body
    ).status_code == 422

    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"
    assert client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact", json=body
    ).status_code == 400

    body = _request()
    body["candidate"]["exposureAvailableAt"] = "2025-12-31T23:00:00"  # type: ignore[index]
    assert client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact", json=body
    ).status_code == 400


def test_candidate_impact_rejects_candidate_already_in_baseline(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["candidate"]["instrumentId"] = 1  # type: ignore[index]
    body["candidate"]["qualityExposureKey"] = QUALITY_BASE_KEY  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact", json=body
    )
    assert response.status_code == 400
    assert "ya pertenece" in response.json()["detail"]

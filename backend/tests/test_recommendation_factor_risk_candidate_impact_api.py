from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.api import recommendation_factor_risk_candidate_impact as candidate_api
from app.main import app


client = TestClient(app)
AS_OF = "2026-01-01T00:00:00+00:00"
AVAILABLE_AT = "2025-12-31T23:00:00+00:00"


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
        return {
            "portfolio_state_key": "a" * 64,
            "artifact": {"reconciled": True},
        }


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
            "positions": [
                {"instrumentId": 1, "symbol": "AAA", "weight": 0.6},
            ],
        }

    def validate_artifact(self, artifact: dict[str, object]) -> dict[str, object]:
        return artifact


def _install_evidence(monkeypatch) -> None:
    monkeypatch.setattr(candidate_api, "_reconciliation_repository", _ReconciliationRepository())
    monkeypatch.setattr(candidate_api, "_valuation_repository", _ValuationRepository())
    monkeypatch.setattr(candidate_api, "_weight_service", _WeightService())


def _candidate() -> dict[str, object]:
    return {
        "instrumentId": 2,
        "symbol": "BBB",
        "weight": 0.2,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:2:2025-12-31",
        "factors": {"value": -1.0, "quality": 0.2},
    }


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


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "diagnostic_ready",
        "asOf": AS_OF,
        "candidate": _candidate(),
        "baselineInvestedWeight": 0.6,
        "baselineCashWeight": 0.4,
        "postInvestedWeight": 0.8,
        "postCashWeight": 0.2,
        "comparableFactors": ["value", "quality"],
        "coverageLostFactors": [],
        "baselineWeightedExposures": {"value": 0.6, "quality": 0.12},
        "postWeightedExposures": {"value": 0.4, "quality": 0.16},
        "factorExposureDeltas": {"value": -0.2, "quality": 0.04},
        "baselineComparableGrossExposure": 0.72,
        "postComparableGrossExposure": 0.56,
        "comparableGrossExposureDelta": -0.16,
        "baselineComparableMaxAbsExposure": 0.6,
        "postComparableMaxAbsExposure": 0.4,
        "comparableMaxAbsExposureDelta": -0.2,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": _policy(),
    }
    payload.update(overrides)
    return payload


def _request() -> dict[str, object]:
    return {
        "portfolioId": "portfolio-1",
        "reportingCurrency": "USD",
        "reconciliationKey": "c" * 64,
        "portfolioValuationEvidenceFingerprint": "b" * 64,
        "asOf": AS_OF,
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "exposureAvailableAt": AVAILABLE_AT,
                "source": "pit_factor_store",
                "sourceRef": "factor:1:2025-12-31",
                "factors": {"value": 1.0, "quality": 0.2},
            }
        ],
        "candidate": _candidate(),
    }


def test_candidate_impact_endpoint_preserves_research_only_contract(monkeypatch) -> None:
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
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["covariance"] == "not_estimated_no_marginal_variance_or_risk_contribution_claim"
    assert data["candidate"]["sourceRef"] == "factor:2:2025-12-31"
    assert data["stateIntegrity"]["baselineWeightDerivation"] == "derived_from_reconciled_state_and_sealed_pit_valuation"
    assert data["stateIntegrity"]["baselineCallerSuppliedWeightAccepted"] is False
    assert data["stateIntegrity"]["callerSuppliedSealedFactorsAccepted"] is False
    assert data["stateIntegrity"]["sealedFactorComparison"] == "blocked_until_candidate_has_matching_sealed_pit_evidence"
    assert data["stateIntegrity"]["candidateWeightMeaning"] == "explicit_hypothetical_cash_funded_scenario_not_sizing_advice"
    assert data["stateIntegrity"]["baselineCashWeight"] == 0.4
    assert len(service.calls) == 1
    baseline = service.calls[0]["positions"]
    assert baseline[0].weight == 0.6


def test_candidate_impact_api_rejects_baseline_caller_weight(monkeypatch) -> None:
    _install_evidence(monkeypatch)
    body = _request()
    body["positions"][0]["weight"] = 0.6  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 422


def test_candidate_impact_rejects_sealed_factor_in_baseline_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    body = _request()
    body["positions"][0]["factors"] = {"value": 1.0, "market": 1.2}  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "factores sellados" in response.json()["detail"]
    assert service.calls == []


def test_candidate_impact_rejects_rates_in_baseline_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    body = _request()
    body["positions"][0]["factors"] = {"value": 1.0, "rates": 0.5}  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "factores sellados" in response.json()["detail"]
    assert service.calls == []


def test_candidate_impact_rejects_sealed_factor_in_candidate_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    body = _request()
    body["candidate"]["factors"] = {"quality": 0.2, "usd_fx": -1.0}  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "factores sellados" in response.json()["detail"]
    assert service.calls == []


def test_candidate_impact_rejects_rates_in_candidate_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    body = _request()
    body["candidate"]["factors"] = {"quality": 0.2, "rates": -0.4}  # type: ignore[index]
    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "factores sellados" in response.json()["detail"]
    assert service.calls == []


def test_candidate_impact_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
    _install_evidence(monkeypatch)
    unsafe_payloads = (
        _payload(advisoryStatus="buy"),
        _payload(productionEligible=True),
        _payload(isWeightingReady=True),
        _payload(policy=_policy(automaticTrading=True)),
        _payload(policy=_policy(automaticProductionPromotion=True)),
        _payload(policy=_policy(covariance="estimated")),
        _payload(policy=_policy(thresholds="calibrated")),
        _payload(baselineCashWeight=float("nan")),
        _payload(postCashWeight=0.5),
        _payload(comparableFactors=[]),
        _payload(coverageLostFactors=["value"], comparableFactors=["value", "quality"]),
        _payload(factorExposureDeltas={"value": 999.0, "quality": 0.04}),
        _payload(candidate={**_candidate(), "sourceRef": ""}),
        _payload(candidate={**_candidate(), "factors": {"value": float("inf")}}),
        _payload(
            comparableFactors=["rates"],
            baselineWeightedExposures={"rates": 0.6},
            postWeightedExposures={"rates": 0.4},
            factorExposureDeltas={"rates": -0.2},
        ),
    )

    for payload in unsafe_payloads:
        monkeypatch.setattr(candidate_api, "candidate_impact_service", _Service(payload))
        response = client.post(
            "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
            json=_request(),
        )
        assert response.status_code == 500


def test_candidate_impact_api_rejects_naive_as_of_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["asOf"] = "2026-01-01T00:00:00"

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_candidate_impact_api_rejects_naive_candidate_evidence_before_service(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["candidate"]["exposureAvailableAt"] = "2025-12-31T23:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []


def test_candidate_impact_api_rejects_candidate_already_in_baseline(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)
    _install_evidence(monkeypatch)
    body = _request()
    body["candidate"]["instrumentId"] = 1  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )
    assert response.status_code == 400
    assert "ya pertenece" in response.json()["detail"]
    assert service.calls == []

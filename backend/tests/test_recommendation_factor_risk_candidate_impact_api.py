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


def _candidate() -> dict[str, object]:
    return {
        "instrumentId": 2,
        "symbol": "BBB",
        "weight": 0.2,
        "exposureAvailableAt": AVAILABLE_AT,
        "source": "pit_factor_store",
        "sourceRef": "factor:2:2025-12-31",
        "factors": {"market": -1.0, "usd_fx": 0.2},
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
        "comparableFactors": ["market", "usd_fx"],
        "coverageLostFactors": [],
        "baselineWeightedExposures": {"market": 0.6, "usd_fx": 0.12},
        "postWeightedExposures": {"market": 0.4, "usd_fx": 0.16},
        "factorExposureDeltas": {"market": -0.2, "usd_fx": 0.04},
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
        "asOf": AS_OF,
        "positions": [
            {
                "instrumentId": 1,
                "symbol": "AAA",
                "weight": 0.6,
                "exposureAvailableAt": AVAILABLE_AT,
                "source": "pit_factor_store",
                "sourceRef": "factor:1:2025-12-31",
                "factors": {"market": 1.0, "usd_fx": 0.2},
            }
        ],
        "candidate": _candidate(),
    }


def test_candidate_impact_endpoint_preserves_research_only_contract(monkeypatch) -> None:
    service = _Service(_payload())
    monkeypatch.setattr(candidate_api, "candidate_impact_service", service)

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
    assert len(service.calls) == 1


def test_candidate_impact_api_fails_closed_on_unsafe_contract(monkeypatch) -> None:
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
        _payload(coverageLostFactors=["market"], comparableFactors=["market", "usd_fx"]),
        _payload(factorExposureDeltas={"market": 999.0, "usd_fx": 0.04}),
        _payload(candidate={**_candidate(), "sourceRef": ""}),
        _payload(candidate={**_candidate(), "factors": {"market": float("inf")}}),
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
    body = _request()
    body["candidate"]["exposureAvailableAt"] = "2025-12-31T23:00:00"  # type: ignore[index]

    response = client.post(
        "/api/v1/recommendations/professional-research/factor-risk/candidate-impact",
        json=body,
    )

    assert response.status_code == 400
    assert service.calls == []

from __future__ import annotations

import copy

import pytest

from app.services.recommendation_shadow_live_decision_research_service import (
    RecommendationShadowLiveDecisionResearchService,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


class FakeAuditService:
    def __init__(self, payload: dict):
        self.payload = payload

    def get(self, *, candidate_id: int) -> dict:
        return copy.deepcopy(self.payload)


def _audit(*, with_uncertainty: bool = True, risk_score: float = 0.25) -> dict:
    candidate = {
        "symbol": "AAPL",
        "asOf": "2026-09-01T15:00:00+00:00",
        "riskContext": {
            "riskScore": risk_score,
            "annualizedVolatility": 0.30,
            "maxDrawdown60d": -0.12,
        },
        "horizons": {
            "30": {
                "horizonDays": 30,
                "expectedExcessReturn": 0.06,
                "modelFingerprint": "c" * 64,
            },
            "90": {
                "horizonDays": 90,
                "expectedExcessReturn": None,
                "modelFingerprint": "d" * 64,
            },
        },
    }
    uncertainty = None
    uncertainty_fingerprint = None
    if with_uncertainty:
        uncertainty_fingerprint = SHA_B
        uncertainty = {
            "horizons": {
                "30": {
                    "horizonDays": 30,
                    "status": "empirical_forward_uncertainty_available",
                    "observationCount": 24,
                    "residualMetrics": {
                        "rmse": 0.04,
                        "mae": 0.03,
                    },
                    "scenarios": {
                        "lowerEmpiricalExcessReturn": -0.01,
                        "medianEmpiricalExcessReturn": 0.05,
                        "upperEmpiricalExcessReturn": 0.12,
                    },
                }
            }
        }
    return {
        "status": "shadow_live_audit_available",
        "candidateFingerprint": SHA_A,
        "uncertaintyFingerprint": uncertainty_fingerprint,
        "candidate": candidate,
        "uncertainty": uncertainty,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "action": None,
    }


def test_build_combines_sealed_prediction_uncertainty_and_risk_without_advice():
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(_audit())
    )

    result = service.build(candidate_id=7)

    assert result["status"] == "shadow_live_decision_research_ready"
    assert result["researchReadyHorizonCount"] == 1
    horizon = result["horizons"]["30"]
    assert horizon["status"] == "decision_research_evidence_ready"
    assert horizon["researchStrength"] == pytest.approx(1.5)
    assert horizon["conservativeResearchStrength"] == pytest.approx(-0.25)
    assert horizon["riskAdjustedResearchStrength"] == pytest.approx(1.125)
    assert horizon["directionDiagnostics"]["lowerScenarioPositive"] is False
    assert result["horizons"]["90"]["status"] == "not_applicable_no_live_prediction"
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert service.validate_artifact(result) is result


def test_build_reports_pending_when_historical_uncertainty_was_not_sealed():
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(_audit(with_uncertainty=False))
    )

    result = service.build(candidate_id=3)

    assert result["status"] == "shadow_live_decision_research_pending"
    assert result["researchReadyHorizonCount"] == 0
    assert result["horizons"]["30"]["status"] == "pending_empirical_uncertainty"
    assert result["horizons"]["30"]["researchStrength"] is None


def test_validate_artifact_detects_post_creation_tampering():
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(_audit())
    )
    artifact = service.build(candidate_id=9)
    artifact["horizons"]["30"]["expectedExcessReturn"] = 99.0

    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(artifact)


def test_build_rejects_risk_score_outside_normalized_contract():
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(_audit(risk_score=1.2))
    )

    with pytest.raises(ValueError, match="riskScore"):
        service.build(candidate_id=1)


def test_build_rejects_scenario_order_corruption():
    payload = _audit()
    payload["uncertainty"]["horizons"]["30"]["scenarios"] = {
        "lowerEmpiricalExcessReturn": 0.10,
        "medianEmpiricalExcessReturn": 0.05,
        "upperEmpiricalExcessReturn": 0.01,
    }
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(payload)
    )

    with pytest.raises(ValueError, match="escenarios empíricos"):
        service.build(candidate_id=2)


def test_build_fails_closed_if_upstream_audit_attempts_advice():
    payload = _audit()
    payload["productionEligible"] = True
    service = RecommendationShadowLiveDecisionResearchService(
        audit_service=FakeAuditService(payload)
    )

    with pytest.raises(ValueError, match="productionEligible"):
        service.build(candidate_id=2)

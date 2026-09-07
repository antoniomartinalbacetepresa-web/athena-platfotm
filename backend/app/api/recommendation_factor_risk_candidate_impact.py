from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_factor_risk_candidate_impact_service import (
    RecommendationFactorRiskCandidateImpactService,
)
from app.services.recommendation_factor_risk_service import FactorRiskPositionInput


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

candidate_impact_service = RecommendationFactorRiskCandidateImpactService()


class FactorRiskPositionRequest(BaseModel):
    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class FactorRiskCandidateImpactRequest(BaseModel):
    asOf: datetime
    positions: list[FactorRiskPositionRequest] = Field(min_length=1, max_length=499)
    candidate: FactorRiskPositionRequest


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _to_input(item: FactorRiskPositionRequest, prefix: str) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=item.instrumentId,
        symbol=item.symbol,
        weight=item.weight,
        exposure_available_at=_aware_utc(item.exposureAvailableAt, f"{prefix}.exposureAvailableAt"),
        source=item.source,
        source_ref=item.sourceRef,
        factors=dict(item.factors),
    )


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact violó no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact intentó habilitar ponderación.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió política inválida.")
    expected_policy = {
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
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            raise HTTPException(status_code=500, detail=f"Factor Risk Candidate Impact perdió garantía: {key}.")

    numeric_fields = (
        "baselineInvestedWeight",
        "baselineCashWeight",
        "postInvestedWeight",
        "postCashWeight",
        "baselineComparableGrossExposure",
        "postComparableGrossExposure",
        "comparableGrossExposureDelta",
        "baselineComparableMaxAbsExposure",
        "postComparableMaxAbsExposure",
        "comparableMaxAbsExposureDelta",
    )
    if any(not _finite_number(payload.get(field)) for field in numeric_fields):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió métricas no finitas.")
    if abs(float(payload["baselineInvestedWeight"]) + float(payload["baselineCashWeight"]) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió baseline incoherente.")
    if abs(float(payload["postInvestedWeight"]) + float(payload["postCashWeight"]) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió post-cartera incoherente.")
    if float(payload["postInvestedWeight"]) <= float(payload["baselineInvestedWeight"]):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact perdió el incremento explícito de inversión.")
    if float(payload["postCashWeight"]) >= float(payload["baselineCashWeight"]):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact no refleja financiación desde efectivo.")

    comparable = payload.get("comparableFactors")
    coverage_lost = payload.get("coverageLostFactors")
    before = payload.get("baselineWeightedExposures")
    after = payload.get("postWeightedExposures")
    deltas = payload.get("factorExposureDeltas")
    if (
        not isinstance(comparable, list)
        or not comparable
        or any(not isinstance(name, str) or not name for name in comparable)
        or not isinstance(coverage_lost, list)
        or any(not isinstance(name, str) or not name for name in coverage_lost)
        or not isinstance(before, dict)
        or not isinstance(after, dict)
        or not isinstance(deltas, dict)
    ):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió comparación inválida.")
    if len(set(comparable)) != len(comparable) or set(comparable) & set(coverage_lost):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió factores incoherentes.")
    if set(before) != set(comparable) or set(after) != set(comparable) or set(deltas) != set(comparable):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió mapas factoriales incompletos.")
    for factor in comparable:
        values = (before.get(factor), after.get(factor), deltas.get(factor))
        if any(not _finite_number(value) for value in values):
            raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió exposición no finita.")
        if abs((float(after[factor]) - float(before[factor])) - float(deltas[factor])) > 1e-9:
            raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió delta factorial incoherente.")

    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact perdió evidencia del candidato.")
    required_candidate = (
        "instrumentId",
        "symbol",
        "weight",
        "exposureAvailableAt",
        "source",
        "sourceRef",
        "factors",
    )
    if any(candidate.get(field) in (None, "") for field in required_candidate):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió provenance PIT incompleta.")
    if not _finite_number(candidate.get("weight")) or float(candidate["weight"]) <= 0.0:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió peso de candidato inválido.")
    factors = candidate.get("factors")
    if not isinstance(factors, dict) or not factors or any(not _finite_number(value) for value in factors.values()):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió factores de candidato inválidos.")


@router.post("/factor-risk/candidate-impact")
def post_factor_risk_candidate_impact(
    request: FactorRiskCandidateImpactRequest,
) -> dict[str, object]:
    """Measure explicit cash-funded candidate factor impact without sizing advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    positions = tuple(_to_input(item, "positions") for item in request.positions)
    candidate = _to_input(request.candidate, "candidate")

    try:
        result = candidate_impact_service.evaluate(
            as_of=as_of,
            positions=positions,
            candidate=candidate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar el impacto factorial PIT del candidato.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}

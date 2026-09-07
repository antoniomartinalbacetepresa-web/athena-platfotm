from __future__ import annotations

from datetime import datetime, timezone
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

service = RecommendationPerformanceAttributionService()


class EvidenceRequest(BaseModel):
    value: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class FactorContributionRequest(BaseModel):
    factor: str = Field(min_length=1)
    contribution: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class PerformanceAttributionRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    asOf: datetime
    periodStart: datetime
    periodEnd: datetime
    totalReturn: EvidenceRequest
    marketContribution: EvidenceRequest
    fxContribution: EvidenceRequest
    factorContributions: list[FactorContributionRequest] = Field(default_factory=list, max_length=20)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=500, detail=f"Performance Attribution devolvió {field} inválido.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HTTPException(status_code=500, detail=f"Performance Attribution devolvió {field} no finito.")
    return numeric


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("module") != "performance_attribution":
        raise HTTPException(status_code=500, detail="Performance Attribution devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Performance Attribution violó no_advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Performance Attribution intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Performance Attribution intentó habilitar weighting.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Performance Attribution devolvió política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Performance Attribution intentó habilitar trading.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Performance Attribution intentó auto-promoción.")
    if policy.get("causalClaim") != "forbidden_arithmetic_attribution_only":
        raise HTTPException(status_code=500, detail="Performance Attribution intentó atribución causal no validada.")
    if policy.get("residualInterpretation") != "unexplained_not_automatic_stock_selection_alpha":
        raise HTTPException(status_code=500, detail="Performance Attribution interpretó residual como alpha.")
    if policy.get("fx") != "explicit_not_silently_neutralized":
        raise HTTPException(status_code=500, detail="Performance Attribution perdió seguridad FX.")

    required_text = ("instrumentId", "symbol", "asOf", "periodStart", "periodEnd")
    if any(payload.get(key) in (None, "") for key in required_text):
        raise HTTPException(status_code=500, detail="Performance Attribution perdió identidad o periodo.")

    total = _assert_finite(payload.get("totalReturn"), "totalReturn")
    market = _assert_finite(payload.get("marketContribution"), "marketContribution")
    fx = _assert_finite(payload.get("fxContribution"), "fxContribution")
    explained = _assert_finite(payload.get("explainedReturn"), "explainedReturn")
    residual = _assert_finite(payload.get("residualReturn"), "residualReturn")

    factors = payload.get("factorContributions")
    if not isinstance(factors, dict):
        raise HTTPException(status_code=500, detail="Performance Attribution devolvió factores inválidos.")
    factor_sum = 0.0
    for name, value in factors.items():
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=500, detail="Performance Attribution devolvió factor sin identidad.")
        factor_sum += _assert_finite(value, f"factorContributions.{name}")

    if not math.isclose(explained, market + fx + factor_sum, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Performance Attribution devolvió explainedReturn inconsistente.")
    if not math.isclose(total, explained + residual, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Performance Attribution devolvió residual inconsistente.")

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        raise HTTPException(status_code=500, detail="Performance Attribution perdió provenance.")
    for key in ("totalReturn", "marketContribution", "fxContribution", "factorContributions"):
        if key not in evidence:
            raise HTTPException(status_code=500, detail="Performance Attribution devolvió provenance incompleta.")


@router.post("/performance-attribution")
def post_performance_attribution(request: PerformanceAttributionRequest) -> dict[str, object]:
    """Perform arithmetic, PIT, provenance-bound return attribution without advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")

    def evidence(item: EvidenceRequest, field: str) -> AttributionEvidence:
        return AttributionEvidence(
            value=item.value,
            available_at=_aware_utc(item.availableAt, f"{field}.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
        )

    factors = tuple(
        FactorContributionEvidence(
            factor=item.factor,
            contribution=item.contribution,
            available_at=_aware_utc(item.availableAt, "factorContributions.availableAt"),
            source=item.source,
            source_ref=item.sourceRef,
        )
        for item in request.factorContributions
    )

    try:
        result = service.evaluate(
            as_of=as_of,
            item=RecommendationPerformanceAttributionInput(
                instrument_id=request.instrumentId,
                symbol=request.symbol,
                period_start=period_start,
                period_end=period_end,
                total_return=evidence(request.totalReturn, "totalReturn"),
                market_contribution=evidence(request.marketContribution, "marketContribution"),
                fx_contribution=evidence(request.fxContribution, "fxContribution"),
                factor_contributions=factors,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular Performance Attribution PIT.") from exc

    payload = result.to_api_dict()
    _assert_contract(payload)
    return {"data": payload}

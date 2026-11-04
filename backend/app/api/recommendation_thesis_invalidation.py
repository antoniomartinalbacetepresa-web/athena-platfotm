from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_thesis_invalidation_service import (
    RecommendationThesisCriterionInput,
    RecommendationThesisInvalidationService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

thesis_invalidation_service = RecommendationThesisInvalidationService()


class ThesisCriterionRequest(BaseModel):
    name: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    threshold: float
    observedValue: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class ThesisInvalidationRequest(BaseModel):
    symbol: str = Field(min_length=1)
    asOf: datetime
    criteria: list[ThesisCriterionRequest] = Field(min_length=1, max_length=50)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Thesis Invalidation violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Thesis Invalidation intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Thesis Invalidation intentó habilitar ponderación.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Thesis Invalidation devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Thesis Invalidation intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Thesis Invalidation intentó promover producción automáticamente.")
    if policy.get("priceOnlyInvalidation") != "forbidden":
        raise HTTPException(status_code=500, detail="Thesis Invalidation perdió la barrera contra venta basada solo en precio.")
    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise HTTPException(status_code=500, detail="Thesis Invalidation devolvió criterios inválidos.")
    required = ("name", "metric", "operator", "threshold", "observedValue", "breached", "availableAt", "source", "sourceRef")
    for criterion in criteria:
        if not isinstance(criterion, dict) or any(criterion.get(field) in (None, "") for field in required):
            raise HTTPException(status_code=500, detail="Thesis Invalidation devolvió evidencia PIT incompleta.")


@router.post("/thesis-invalidation")
def post_thesis_invalidation(request: ThesisInvalidationRequest) -> dict[str, object]:
    """Evaluate explicit PIT thesis-break criteria without creating sell advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    criteria: list[RecommendationThesisCriterionInput] = []
    for item in request.criteria:
        criteria.append(
            RecommendationThesisCriterionInput(
                name=item.name,
                metric=item.metric,
                operator=item.operator,
                threshold=item.threshold,
                observed_value=item.observedValue,
                available_at=_aware_utc(item.availableAt, "criteria.availableAt"),
                source=item.source,
                source_ref=item.sourceRef,
            )
        )
    try:
        result = thesis_invalidation_service.evaluate(
            symbol=request.symbol,
            as_of=as_of,
            criteria=tuple(criteria),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar Thesis Invalidation PIT de ATHENA.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Thesis Invalidation devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}

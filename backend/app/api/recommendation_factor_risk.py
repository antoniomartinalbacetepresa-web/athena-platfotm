from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

factor_risk_service = RecommendationFactorRiskService()


class FactorRiskPositionRequest(BaseModel):
    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class FactorRiskResearchRequest(BaseModel):
    asOf: datetime
    positions: list[FactorRiskPositionRequest] = Field(min_length=1, max_length=500)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Factor Risk violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar ponderación.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó promover producción automáticamente.")
    if policy.get("identity") != "duplicate_instrument_or_symbol_forbidden":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía de identidad.")
    if policy.get("fx") != "usd_fx_is_explicit_factor_not_silently_netting_currency_risk":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía explícita de FX.")

    exposures = payload.get("weightedExposures")
    if not isinstance(exposures, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió exposiciones inválidas.")
    for name, value in exposures.items():
        if not isinstance(name, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió exposición no numérica.")

    count = payload.get("positionCount")
    invested = payload.get("investedWeight")
    cash = payload.get("cashWeight")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió positionCount inválido.")
    for value in (invested, cash, payload.get("grossFactorExposure"), payload.get("maxAbsoluteFactorExposure")):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió métricas inválidas.")


@router.post("/factor-risk")
def post_factor_risk(request: FactorRiskResearchRequest) -> dict[str, object]:
    """Measure explicit PIT portfolio factor exposure without sizing or trade advice."""

    as_of = _aware_utc(request.asOf, "asOf")
    positions: list[FactorRiskPositionInput] = []
    for item in request.positions:
        positions.append(
            FactorRiskPositionInput(
                instrument_id=item.instrumentId,
                symbol=item.symbol,
                weight=item.weight,
                exposure_available_at=_aware_utc(
                    item.exposureAvailableAt,
                    "positions.exposureAvailableAt",
                ),
                source=item.source,
                source_ref=item.sourceRef,
                factors=dict(item.factors),
            )
        )

    try:
        result = factor_risk_service.evaluate(
            as_of=as_of,
            positions=tuple(positions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar Factor Risk PIT de ATHENA.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió un contrato inválido.")
    _assert_contract(payload)
    return {"data": payload}

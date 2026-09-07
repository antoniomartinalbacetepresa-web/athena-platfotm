from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_production_read_service import (
    RecommendationProductionReadService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/production",
    tags=["recommendations-production-read"],
)

production_read_service = RecommendationProductionReadService()


def _effective_as_of(as_of: datetime | None) -> datetime:
    value = as_of if as_of is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.get("/latest")
def get_latest_production_state(
    symbol: str | None = Query(None, min_length=1),
    instrument_id: int | None = Query(None, ge=1, alias="instrumentId"),
    as_of: datetime | None = Query(
        None,
        description=(
            "Corte PIT. Sólo devuelve autorizaciones productivas que ya estaban "
            "persistidas y eran conocidas en ese instante."
        ),
    ),
) -> dict[str, object]:
    """Return persisted production state without exposing any promotion/write path."""

    effective_as_of = _effective_as_of(as_of)
    try:
        payload = production_read_service.resolve_latest(
            as_of=effective_as_of,
            symbol=symbol,
            instrument_id=instrument_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar el estado productivo persistido de ATHENA.",
        ) from exc

    if payload.get("readOnly") is not True or payload.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="La lectura productiva violó el contrato de seguridad de ATHENA.",
        )

    recommendation = payload.get("recommendation")
    if recommendation is not None:
        if not isinstance(recommendation, dict):
            raise HTTPException(status_code=500, detail="Recomendación productiva inválida.")
        if (
            recommendation.get("productionEligible") is not True
            or recommendation.get("allocationEligible") is not False
            or recommendation.get("automaticTrading") is not False
        ):
            raise HTTPException(
                status_code=500,
                detail="Contrato de recomendación productiva inválido.",
            )

    allocation = payload.get("allocation")
    if allocation is not None:
        if not isinstance(allocation, dict):
            raise HTTPException(status_code=500, detail="Allocation productivo inválido.")
        if (
            allocation.get("productionEligible") is not True
            or allocation.get("allocationEligible") is not True
            or allocation.get("executionEligible") is not False
            or allocation.get("orderRoutingEligible") is not False
            or allocation.get("automaticTrading") is not False
        ):
            raise HTTPException(
                status_code=500,
                detail="Contrato de allocation productivo inválido.",
            )

    return {"data": payload}

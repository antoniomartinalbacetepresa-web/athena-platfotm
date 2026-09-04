from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_shadow_operational_live_cycle_service import (
    RecommendationShadowOperationalLiveCycleService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/learning",
    tags=["recommendations"],
)

operational_live_cycle_service = RecommendationShadowOperationalLiveCycleService()


def _effective_as_of(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return result.astimezone(timezone.utc)


def _parse_horizons(value: str) -> tuple[int, ...]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Se requiere al menos un horizonte.")
    try:
        horizons = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="horizons debe contener enteros positivos separados por comas.",
        ) from exc
    if any(horizon <= 0 for horizon in horizons):
        raise HTTPException(status_code=400, detail="Todos los horizontes deben ser positivos.")
    if len(set(horizons)) != len(horizons):
        raise HTTPException(status_code=400, detail="Los horizontes no pueden repetirse.")
    return horizons


def _assert_operational_shadow_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(
            status_code=500,
            detail="El live cycle operativo violó el contrato no-advice de ATHENA.",
        )
    if payload.get("productionEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail="El live cycle operativo no puede habilitar producción.",
        )
    if payload.get("recommendationCandidateReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="El live cycle operativo no puede habilitar recomendaciones.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="El live cycle devolvió política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="El live cycle operativo no puede habilitar trading automático.",
        )
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(
            status_code=500,
            detail="El live cycle operativo no puede promover producción automáticamente.",
        )


@router.post("/shadow-live-cycle")
def run_shadow_live_cycle(
    symbol: str = Query(..., min_length=1),
    benchmark_symbol: str = Query("SPY", min_length=1),
    as_of: datetime | None = Query(None),
    horizons: str = Query("7,30,90,180,365"),
) -> dict[str, object]:
    """Capture and persist one real live-shadow candidate using a trusted frozen cohort."""

    effective_as_of = _effective_as_of(as_of)
    effective_horizons = _parse_horizons(horizons)
    try:
        payload = operational_live_cycle_service.run(
            symbol=symbol,
            as_of=effective_as_of,
            benchmark_symbol=benchmark_symbol,
            horizons=effective_horizons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo ejecutar el live cycle shadow operativo de ATHENA.",
        ) from exc

    _assert_operational_shadow_contract(payload)
    return {"data": payload}

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_shadow_research_pipeline_service import (
    RecommendationShadowResearchPipelineService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/learning",
    tags=["recommendations"],
)

research_pipeline_service = RecommendationShadowResearchPipelineService()


def _effective_as_of(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return result


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


@router.get("/shadow-research-readiness")
def get_shadow_research_readiness(
    as_of: datetime | None = Query(None),
    horizons: str = Query("7,30,90,180,365"),
) -> dict[str, object]:
    """Run the PIT research pipeline without producing investment advice."""

    effective_as_of = _effective_as_of(as_of)
    effective_horizons = _parse_horizons(horizons)
    try:
        payload = research_pipeline_service.evaluate(
            as_of=effective_as_of,
            horizons=effective_horizons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar la preparación shadow de ATHENA.",
        ) from exc

    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow violó el contrato no-advice de ATHENA.",
        )
    if payload.get("productionEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow no puede habilitar producción.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("productionEligibility") is not False:
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow devolvió una política de producción inválida.",
        )
    return {"data": payload}

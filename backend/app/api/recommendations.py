from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)


router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["recommendations"],
)

learning_status_service = RecommendationLearningStatusService()


@router.get("/learning/status")
def get_learning_status(
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte del diagnóstico. Si se omite se usa la hora UTC actual."
        ),
    ),
    model_version: str | None = Query(
        None,
        min_length=1,
        alias="modelVersion",
    ),
    horizon_days: int | None = Query(
        None,
        ge=1,
        alias="horizonDays",
    ),
) -> dict[str, object]:
    effective_as_of = as_of if as_of is not None else datetime.now(timezone.utc)

    if effective_as_of.tzinfo is None or effective_as_of.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail="as_of debe incluir zona horaria.",
        )

    normalized_model_version = (
        model_version.strip()
        if model_version is not None
        else None
    )

    try:
        status = learning_status_service.get_status(
            as_of=effective_as_of,
            model_version=normalized_model_version,
            horizon_days=horizon_days,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el estado de aprendizaje de ATHENA.",
        ) from exc

    return {
        "data": status,
    }

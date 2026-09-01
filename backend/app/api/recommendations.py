from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)
from app.services.recommendation_market_signal_service import (
    RecommendationMarketSignalService,
)


router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["recommendations"],
)

learning_status_service = RecommendationLearningStatusService()
market_signal_service = RecommendationMarketSignalService()


def _effective_as_of(as_of: datetime | None) -> datetime:
    value = as_of if as_of is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail="as_of debe incluir zona horaria.",
        )
    return value


@router.get("/diagnostics/market-signal")
def get_market_signal_diagnostic(
    symbol: str = Query(
        ...,
        min_length=1,
        description="Símbolo del instrumento que se desea diagnosticar.",
    ),
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte point-in-time. Si se omite se usa la hora UTC actual."
        ),
    ),
) -> dict[str, object]:
    """Return transparent PIT market features without issuing investment advice."""

    effective_as_of = _effective_as_of(as_of)

    try:
        diagnostic = market_signal_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el diagnóstico de mercado de ATHENA.",
        ) from exc

    payload = diagnostic.to_api_dict()
    if payload.get("productionEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail=(
                "El diagnóstico de mercado violó la política de seguridad: "
                "no puede ser productivo antes de la calibración completa."
            ),
        )

    return {
        "data": payload,
        "advisoryStatus": "diagnostic_only",
    }


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
    effective_as_of = _effective_as_of(as_of)

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

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.fred_alfred_service import FredAlfredService
from app.services.public_macro_service import PublicMacroService
from app.services.recommendation_macro_pit_import_service import (
    RecommendationMacroPitImportService,
)


router = APIRouter(
    prefix="/api/v1/macro",
    tags=["macro"],
)


class FredAlfredPitImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seriesId: str = Field(min_length=1)
    observationStart: str | None = None
    observationEnd: str | None = None
    realtimeStart: str = Field(min_length=10, max_length=10)
    realtimeEnd: str = Field(min_length=10, max_length=10)
    asOf: datetime


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


@router.get("/world-bank")
def get_world_bank_indicator(
    country: str = Query(..., min_length=1),
    indicator: str = Query(..., min_length=1),
    start_year: int | None = Query(None),
    end_year: int | None = Query(None),
) -> dict[str, object]:
    service = PublicMacroService()
    try:
        return {
            "data": service.get_world_bank_indicator(
                country=country,
                indicator=indicator,
                start_year=start_year,
                end_year=end_year,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener datos del World Bank.") from exc
    finally:
        service.close()


@router.get("/ecb")
def get_ecb_series(
    flow_ref: str = Query(..., min_length=1),
    key: str = Query(""),
    start_period: str | None = Query(None),
    end_period: str | None = Query(None),
    last_n_observations: int | None = Query(None, ge=1),
    include_history: bool = Query(False),
) -> dict[str, object]:
    service = PublicMacroService()
    try:
        return {
            "data": service.get_ecb_series(
                flow_ref=flow_ref,
                key=key,
                start_period=start_period,
                end_period=end_period,
                last_n_observations=last_n_observations,
                include_history=include_history,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron obtener datos del BCE.") from exc
    finally:
        service.close()


@router.post("/fred-alfred/pit-import")
def import_fred_alfred_pit(request: FredAlfredPitImportRequest) -> dict[str, object]:
    """Persist revision-aware ALFRED evidence from the server-side connector only."""

    as_of = _aware_utc(request.asOf, "asOf")
    service = FredAlfredService()
    if not service.configured:
        service.close()
        raise HTTPException(
            status_code=503,
            detail="FRED_API_KEY no está configurada en el backend; no se expone ni se acepta desde el cliente.",
        )
    try:
        payload = service.get_observations(
            series_id=request.seriesId,
            observation_start=request.observationStart,
            observation_end=request.observationEnd,
            realtime_start=request.realtimeStart,
            realtime_end=request.realtimeEnd,
        )
        result = RecommendationMacroPitImportService().import_fred_alfred_payload(
            series_id=request.seriesId,
            payload=payload,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener/persistir evidencia FRED/ALFRED PIT.",
        ) from exc
    finally:
        service.close()

    if (
        result.get("advisoryStatus") != "no_advice"
        or result.get("productionEligible") is not False
        or result.get("isWeightingReady") is not False
    ):
        raise HTTPException(status_code=500, detail="Macro PIT import violó límites de seguridad.")
    policy = result.get("policy")
    if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Macro PIT import intentó habilitar trading.")
    return {"data": result}

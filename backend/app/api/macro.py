from fastapi import APIRouter, HTTPException, Query

from app.services.public_macro_service import PublicMacroService


router = APIRouter(
    prefix="/api/v1/macro",
    tags=["macro"],
)


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

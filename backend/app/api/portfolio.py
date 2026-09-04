from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.services.portfolio_correlation_service import PortfolioCorrelationService
from app.services.portfolio_instrument_identity_service import (
    PortfolioInstrumentIdentityService,
)


router = APIRouter(
    prefix="/api/v1/portfolio",
    tags=["portfolio"],
)


@router.get("/instrument-identity")
def get_portfolio_instrument_identity(
    symbol: str = Query(..., min_length=1),
    exchange: str | None = Query(None),
) -> dict[str, object]:
    """Resolve one portfolio listing against ATHENA's canonical catalog.

    A unique symbol can be returned for diagnostics even when exchange identity
    is not verified. Callers must honor isRiskReady=false and must not use that
    diagnostic resolution for portfolio risk, allocation or weighting.
    """
    service = PortfolioInstrumentIdentityService()
    try:
        result = service.resolve(symbol=symbol, exchange=exchange)
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo resolver una identidad canónica verificable.",
        ) from exc


@router.get("/correlation")
def get_portfolio_pair_correlation(
    left_instrument_id: int = Query(..., alias="leftInstrumentId", ge=1),
    right_instrument_id: int = Query(..., alias="rightInstrumentId", ge=1),
    source_provider: str = Query(..., alias="sourceProvider", min_length=1),
    knowledge_cutoff: datetime = Query(..., alias="knowledgeCutoff"),
    observed_from: datetime | None = Query(None, alias="observedFrom"),
    observed_to: datetime | None = Query(None, alias="observedTo"),
) -> dict[str, object]:
    """Return descriptive PIT correlation for two canonical instruments.

    The endpoint never turns correlation into advice, allocation influence or an
    automatic-trading signal. Those policies are also carried in the payload
    returned by PortfolioCorrelationService.
    """
    service = PortfolioCorrelationService()
    try:
        result = service.calculate_pair(
            left_instrument_id=left_instrument_id,
            right_instrument_id=right_instrument_id,
            source_provider=source_provider,
            knowledge_cutoff=knowledge_cutoff,
            observed_from=observed_from,
            observed_to=observed_to,
        )
        return {"data": result.to_api_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo calcular una correlación PIT verificable.",
        ) from exc

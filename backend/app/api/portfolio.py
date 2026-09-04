from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.services.portfolio_correlation_service import PortfolioCorrelationService


router = APIRouter(
    prefix="/api/v1/portfolio",
    tags=["portfolio"],
)


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

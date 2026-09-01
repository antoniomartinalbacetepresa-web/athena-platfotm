from fastapi import APIRouter, HTTPException, Query

from app.services.yahoo_market_service import YahooMarketService
from app.services.yahoo_market_universe_service import (
    YahooMarketUniverseService,
)


router = APIRouter(
    prefix="/api/v1/market",
    tags=["market"],
)

market_service = YahooMarketService()
market_universe_service = YahooMarketUniverseService()


@router.get("/quote")
def get_quote(
    symbol: str = Query(
        ...,
        min_length=1,
    ),
) -> dict[str, object]:
    try:
        quote = market_service.get_quote(symbol)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo obtener la cotización "
                "desde la fuente de mercado."
            ),
        ) from exc

    return {
        "data": quote,
    }


@router.get("/history")
def get_history(
    symbol: str = Query(
        ...,
        min_length=1,
    ),
    from_date: str | None = Query(
        None,
        alias="from",
    ),
    to_date: str | None = Query(
        None,
        alias="to",
    ),
) -> dict[str, object]:
    try:
        history = market_service.get_history(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo obtener el histórico "
                "desde la fuente de mercado."
            ),
        ) from exc

    return {
        "data": history,
    }


@router.get("/universe")
def get_universe() -> dict[str, object]:
    try:
        universe = market_universe_service.get_universe()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo obtener el universo "
                "desde la fuente de mercado."
            ),
        ) from exc

    return {
        "data": universe,
    }

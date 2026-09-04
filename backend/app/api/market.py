from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from app.repositories.fx_rate_repository import FxRateRepository
from app.services.fx_quote_service import FxQuoteService
from app.services.market_weighting_readiness_service import (
    MarketWeightingReadinessService,
)
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)
from app.services.yahoo_market_service import YahooMarketService


router = APIRouter(
    prefix="/api/v1/market",
    tags=["market"],
)

market_service = YahooMarketService()
fx_rate_repository = FxRateRepository()
fx_quote_service = FxQuoteService(
    market_service=market_service,
    repository=fx_rate_repository,
)
market_universe_service = PersistedMarketUniverseService()
market_weighting_readiness_service = MarketWeightingReadinessService()


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


@router.get("/fx/quote")
def get_fx_quote(
    base_currency: str = Query(..., min_length=3, max_length=3, alias="base"),
    quote_currency: str = Query(..., min_length=3, max_length=3, alias="quote"),
) -> dict[str, object]:
    """Return a current FX rate with source and temporal provenance.

    This endpoint is intentionally current-only. Its result must not be
    backdated for historical portfolio or recommendation evaluation.
    """

    try:
        payload = fx_quote_service.get_current_rate(
            base_currency=base_currency,
            quote_currency=quote_currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener una conversión FX trazable.",
        ) from exc

    return {"data": payload}


@router.get("/fx/historical")
def get_historical_fx_quote(
    base_currency: str = Query(..., min_length=3, max_length=3, alias="base"),
    quote_currency: str = Query(..., min_length=3, max_length=3, alias="quote"),
    observed_on: date = Query(..., alias="observedOn"),
    knowledge_cutoff: datetime | None = Query(None, alias="knowledgeCutoff"),
) -> dict[str, object]:
    """Return an exact-date FX observation with PIT provenance.

    When ``knowledgeCutoff`` is supplied, the service may only replay or obtain
    evidence that was already knowable by that timestamp. Without a cutoff the
    endpoint is intended for current portfolio accounting: it may retrieve the
    historical observation now and persist that immutable retrieval for future
    reproducibility.
    """

    try:
        payload = fx_quote_service.get_historical_rate(
            base_currency=base_currency,
            quote_currency=quote_currency,
            observed_on=observed_on,
            knowledge_cutoff=knowledge_cutoff,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener una conversión FX histórica verificable.",
        ) from exc

    return {"data": payload}


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


@router.get("/universe/status")
def get_universe_status() -> dict[str, object]:
    try:
        report = market_universe_service.get_quality_report()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo evaluar la calidad "
                "del universo de mercado."
            ),
        ) from exc

    return {
        "data": report.to_api_dict(),
    }


@router.get("/universe/weighting-readiness")
def get_universe_weighting_readiness() -> dict[str, object]:
    try:
        report = market_weighting_readiness_service.get_report()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo evaluar la preparación de los pesos regionales."
            ),
        ) from exc

    return {
        "data": report.to_api_dict(),
    }

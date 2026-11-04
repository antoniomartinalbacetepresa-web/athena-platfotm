from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from app.repositories.fx_rate_repository import FxRateRepository
from app.services.canonical_weighting_governance_service import (
    CanonicalWeightingGovernanceService,
)
from app.services.fx_quote_service import FxQuoteService
from app.services.market_weighting_readiness_service import (
    MarketWeightingReadinessService,
)
from app.services.persisted_market_universe_service import (
    PersistedMarketUniverseService,
)
from app.services.yahoo_market_service import YahooMarketService
from app.services.market_quote_identity_service import MarketQuoteIdentityService


router = APIRouter(
    prefix="/api/v1/market",
    tags=["market"],
)

market_service = YahooMarketService()
quote_identity_service = MarketQuoteIdentityService()
fx_rate_repository = FxRateRepository()
fx_quote_service = FxQuoteService(
    market_service=market_service,
    repository=fx_rate_repository,
)
market_universe_service = PersistedMarketUniverseService()
market_weighting_readiness_service = MarketWeightingReadinessService()
canonical_weighting_governance_service = CanonicalWeightingGovernanceService()


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

    # A provider quote must belong to the instrument actually requested.
    # Never let provider-supplied identity fields bypass our internal resolver.
    if quote is not None:
        if (
            not isinstance(quote, dict)
            or not isinstance(quote.get("symbol"), str)
            or quote["symbol"].strip().upper() != symbol.strip().upper()
        ):
            raise HTTPException(
                status_code=502,
                detail="La fuente devolvió una cotización de identidad incompatible.",
            )
        quote = {
            key: value
            for key, value in quote.items()
            if key not in {"instrumentId", "canonicalIdentityStatus"}
        }

    # Identity enrichment is optional. A repository outage cannot fabricate a
    # match and must not turn a quote into historical PIT evidence.
    if isinstance(quote, dict) and quote.get("exchange") and quote.get("currency"):
        try:
            identity = quote_identity_service.resolve(quote)
        except Exception:
            identity = {"canonicalIdentityStatus": "unresolved"}
        quote = {**quote, **identity}

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

    providers = sorted({
        str(item.get("sourceProvider")).strip()
        for item in history
        if isinstance(item, dict) and item.get("sourceProvider")
    })
    retrieval_times = sorted({
        str(item.get("retrievedAt")).strip()
        for item in history
        if isinstance(item, dict) and item.get("retrievedAt")
    })

    return {
        "data": history,
        "provenance": {
            "retrievalMode": "current_provider_history",
            "historicalPointInTimeEligible": False,
            "productionCoverageClaimed": False,
            "sourceProviders": providers,
            "retrievedAt": retrieval_times[0] if len(retrieval_times) == 1 else None,
        },
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


@router.get("/universe/active-regional-weights")
def get_active_regional_weights() -> dict[str, object]:
    """Return regional weights only through the human-approval governance gate.

    Diagnostic market-cap weights are deliberately not treated as active.  The
    governance service returns no weights unless the latest approved proposal
    has explicit human approval, intact evidence and an evidence snapshot that
    still matches the current canonical market state.
    """

    try:
        payload = canonical_weighting_governance_service.get_approved_weights()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar la gobernanza de los pesos regionales.",
        ) from exc

    return {"data": payload}


@router.get("/opportunity-pattern-readiness")
def get_opportunity_pattern_readiness(
    symbol: str = Query(..., min_length=1),
) -> dict[str, object]:
    """Inspect live-provider history for pattern readiness; never certify its licence.

    Provider retrieval now connects Market to the Opportunity & Exit Radar's
    evidence requirements. Yahoo history is current-retrieved, not PIT replay;
    this endpoint must not promote it to licensed, split-verified research.
    """
    try:
        history = market_service.get_history(symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar la cobertura del proveedor de mercado.",
        ) from exc

    # Only count records with a matching instrument identity and valid daily
    # close/volume; malformed or mismatched provider records fail closed.
    from datetime import timezone
    from math import isfinite

    normalized = symbol.strip().upper()
    valid_days: set[str] = set()
    provider_names: set[str] = set()
    retrieval_times: set[str] = set()
    invalid_rows = 0
    for row in history:
        if not isinstance(row, dict) or str(row.get("symbol", "")).upper() != normalized:
            invalid_rows += 1
            continue
        try:
            observed = datetime.fromisoformat(str(row["timestamp"]))
            close = float(row["close"])
            volume = float(row["volume"])
            if (observed.tzinfo is None or observed.utcoffset() is None
                    or not isfinite(close) or close <= 0
                    or not isfinite(volume) or volume < 0):
                raise ValueError("invalid daily bar")
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_rows += 1
            continue
        day = observed.astimezone(timezone.utc).date().isoformat()
        if day in valid_days:
            invalid_rows += 1
            continue
        valid_days.add(day)
        if row.get("sourceProvider"):
            provider_names.add(str(row["sourceProvider"]))
        if row.get("retrievedAt"):
            retrieval_times.add(str(row["retrievedAt"]))

    return {
        "data": {
            "symbol": normalized,
            "status": "blocked_unverified_market_evidence",
            "mode": "read_only_research",
            "validDailySessions": len(valid_days),
            "invalidOrDuplicateRows": invalid_rows,
            "minimum20SessionReferenceAvailable": len(valid_days) >= 21,
            "firstObservedDate": min(valid_days) if valid_days else None,
            "lastObservedDate": max(valid_days) if valid_days else None,
            "sourceProviders": sorted(provider_names),
            "retrievedAt": sorted(retrieval_times),
            "licenceVerified": False,
            "corporateActionsIndependentlyVerified": False,
            "historicalPointInTimeEligible": False,
            "patternComputed": False,
            "advisoryStatus": "no_advice",
            "automaticTrading": False,
            "blockers": [
                "Provider licence and redistribution rights not independently verified.",
                "Split/dividend adjustments lack independent reconciliation.",
                "Current-retrieved history cannot be replayed as historical PIT evidence.",
            ],
        }
    }

from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Query

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
from app.services.pilot_evidence import EvidenceRejected, validate_pilot_history
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
            "historyStatus": "available_unverified" if history else "empty",
            "observationCount": len(history),
            "sourceProviders": providers,
            "retrievedAt": retrieval_times[0] if len(retrieval_times) == 1 else None,
        },
    }


@router.post("/history/pilot-validation")
def validate_pilot_history_api(payload: dict = Body(...)) -> dict[str, object]:
    """Validate supplied historical bars for a read-only research preview.

    This endpoint does not retrieve data, verify provider contracts, or persist
    research. Client-supplied usageAuthorized is never independent proof.
    Limit input size to avoid expensive untrusted historical submissions.
    """
    observations = payload.get("observations")
    sessions = payload.get("expectedSessions")
    if (not isinstance(observations, list) or not isinstance(sessions, list)
            or len(observations) > 400 or len(sessions) > 400):
        raise HTTPException(status_code=422, detail="Invalid or oversized pilot history")
    try:
        report = validate_pilot_history(
            observations, expected_sessions=sessions, now=datetime.now(timezone.utc),
        )
    except (EvidenceRejected, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "data": report,
        "provenance": {
            "status": "unverified_client_supplied",
            "providerRightsIndependentlyVerified": False,
            "historicalPointInTimeEligible": False,
            "productionCoverageClaimed": False,
            "orderExecutionAllowed": False,
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
    eligible_lows: dict[str, float] = {}
    checked_at = datetime.now(timezone.utc)
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
                    or observed > checked_at
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
        # Diagnostic only: require an actual low, never substitute the close.
        # A later observation must not enter its own 25-session reference.
        low_value = row.get("low")
        if (isinstance(low_value, (int, float)) and not isinstance(low_value, bool)
                and isfinite(low_value) and 0 < low_value <= close):
            eligible_lows[day] = float(low_value)
        if row.get("sourceProvider"):
            provider_names.add(str(row["sourceProvider"]))
        if row.get("retrievedAt"):
            retrieval_times.add(str(row["retrievedAt"]))

    first_day = min(valid_days) if valid_days else None
    last_day = max(valid_days) if valid_days else None
    calendar_span_days = ((date.fromisoformat(last_day) - date.fromisoformat(first_day)).days + 1) if first_day and last_day else 0
    latest_age_days = (checked_at.date() - date.fromisoformat(last_day)).days if last_day else None
    # Calendar gaps are diagnostic only: weekends/holidays are not missing
    # exchange sessions, and exchange-specific calendars are not certified.
    ordered_days = sorted(date.fromisoformat(day) for day in valid_days)
    largest_gap_days = max(
        ((right - left).days - 1 for left, right in zip(ordered_days, ordered_days[1:])),
        default=0,
    )
    gap_intervals = sum(
        (right - left).days > 1 for left, right in zip(ordered_days, ordered_days[1:])
    )

    # Use the preceding 25 distinct daily sessions; never include the
    # evaluation session in the reference minimum (look-ahead prevention).
    last_26 = sorted(valid_days)[-26:]
    reference_complete = (
        len(last_26) == 26 and all(day in eligible_lows for day in last_26)
    )
    previous_25_low = (
        min(eligible_lows[day] for day in last_26[:-1])
        if reference_complete else None
    )

    return {
        "data": {
            "symbol": normalized,
            "previous25SessionLowDiagnostic": previous_25_low,
            "previous25SessionReferenceComplete": reference_complete,
            "previous25SessionEvaluationDate": last_26[-1] if reference_complete else None,
            "previous25SessionReferenceEndsOn": last_26[-2] if reference_complete else None,
            "previous25SessionSignalEligible": False,
            "status": "blocked_unverified_market_evidence",
            "mode": "read_only_research",
            "validDailySessions": len(valid_days),
            "invalidOrDuplicateRows": invalid_rows,
            "minimum20SessionReferenceAvailable": len(valid_days) >= 21,
            "firstObservedDate": first_day,
            "lastObservedDate": last_day,
            "calendarSpanDays": calendar_span_days,
            "latestObservationAgeCalendarDays": latest_age_days,
            "largestUnobservedCalendarGapDays": largest_gap_days,
            "unobservedCalendarGapIntervals": gap_intervals,
            "exchangeSessionCalendarVerified": False,
            "history365CalendarSpanAvailable": calendar_span_days >= 365,
            "history365SessionCompletenessVerified": False,
            "checkedAt": checked_at.isoformat(),
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

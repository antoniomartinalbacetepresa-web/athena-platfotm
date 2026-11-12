"""Opt-in, read-only audit of live Market -> News -> ATHENA HTTP responses.

Checks coverage and internal contracts, NOT provider authenticity, licensing,
Ollama execution, predictive skill or production authorization. No writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODULES = frozenset({
    "expectationsGap", "reverseValuation", "scenarioAsymmetry", "catalysts",
    "thesisInvalidation", "factorRisk", "performanceAttribution",
    "investmentJournal", "devilsAdvocate", "athenaRadar", "dividendTotalReturn",
})


class AuditBlocked(ValueError):
    """Safe failure: never expose a provider error or private backend URL."""


def _timestamp(value: object, *, now: datetime) -> datetime:
    if not isinstance(value, str):
        raise AuditBlocked("Missing timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AuditBlocked("Invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuditBlocked("Timestamp has no timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + timedelta(minutes=5):
        raise AuditBlocked("Future timestamp")
    return parsed


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise AuditBlocked("Unexpected response shape")
    return value


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _https_article_url(value: object) -> bool:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and bool(parsed.hostname)
            and "." in parsed.hostname and parsed.username is None
            and parsed.password is None and (port is None or 1 <= port <= 65535))


def _history_audit(fetch, *, symbol: str, now: datetime) -> dict:
    # Ask for more than 365 days to allow non-trading days at the window edge.
    # This is provider history retrieved NOW, not historical PIT replay.
    start = now.date() - timedelta(days=400)
    response = _object(fetch("/api/v1/market/history", {
        "symbol": symbol, "from": start.isoformat(), "to": now.date().isoformat(),
    }))
    provenance = _object(response.get("provenance"))
    if (provenance.get("retrievalMode") != "current_provider_history"
            or provenance.get("historicalPointInTimeEligible") is not False
            or provenance.get("productionCoverageClaimed") is not False):
        raise AuditBlocked("History falsely claims PIT or production authority")
    rows = response.get("data")
    if not isinstance(rows, list):
        raise AuditBlocked("History observations missing")
    dates = set()
    providers = set()
    missing_adjusted = split_events = dividend_events = 0
    for item in rows:
        point = _object(item)
        if _text(point.get("symbol")).upper() != symbol:
            raise AuditBlocked("History instrument mismatch")
        close = point.get("close")
        if type(close) not in (int, float) or not math.isfinite(close) or close <= 0:
            raise AuditBlocked("History has invalid closing price")
        provider = _text(point.get("sourceProvider"))
        if not provider:
            raise AuditBlocked("History source missing")
        providers.add(provider)
        observed = _timestamp(point.get("timestamp"), now=now)
        retrieved = _timestamp(point.get("retrievedAt"), now=now)
        if observed > retrieved + timedelta(minutes=5):
            raise AuditBlocked("History observation after retrieval")
        session = observed.date()
        if session < start - timedelta(days=1) or session > now.date():
            raise AuditBlocked("History observation outside requested window")
        if session in dates:
            raise AuditBlocked("Duplicate UTC history session date")
        dates.add(session)
        adjusted = point.get("adjustedClose")
        if adjusted is None:
            missing_adjusted += 1
        elif type(adjusted) not in (int, float) or not math.isfinite(adjusted) or adjusted <= 0:
            raise AuditBlocked("Invalid adjusted close")
        for field in ("dividend", "stockSplit"):
            value = point.get(field)
            if value is not None:
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise AuditBlocked("Invalid corporate action")
                if field == "dividend":
                    dividend_events += 1
                else:
                    split_events += 1
    declared = provenance.get("sourceProviders")
    if not isinstance(declared, list) or declared != sorted(providers):
        raise AuditBlocked("History provider inventory mismatch")
    retrieval = provenance.get("retrievedAt")
    if retrieval is not None:
        _timestamp(retrieval, now=now)
        if any(item.get("retrievedAt") != retrieval for item in rows):
            raise AuditBlocked("History retrieval provenance mismatch")
    ordered = sorted(dates)
    gaps = []
    if ordered:
        day = ordered[0]
        while day <= ordered[-1]:
            # Exchange-specific holidays and local session timezones are NOT
            # available here; these are candidates, not proven missing bars.
            if day.weekday() < 5 and day not in dates:
                gaps.append(day.isoformat())
            day += timedelta(days=1)
    depth = (ordered[-1] - ordered[0]).days if len(ordered) > 1 else 0
    latest_age_days = (now.date() - ordered[-1]).days if ordered else None
    # A year-long span ending months ago is not current 365-day coverage.
    # Seven calendar days allow weekends/market holidays; this remains only
    # a candidate, never proof of session continuity or provider licensing.
    current_depth_candidate = (
        depth >= 365 and latest_age_days is not None
        and 0 <= latest_age_days <= 7
        and ordered[0] <= now.date() - timedelta(days=365)
    )
    return {
        "requestedLookbackDays": 400, "rows": len(rows),
        "firstObservationUtcDate": ordered[0].isoformat() if ordered else None,
        "lastObservationUtcDate": ordered[-1].isoformat() if ordered else None,
        "observedCalendarDepthDays": depth,
        "has365CalendarDaySpan": depth >= 365,
        "latestObservationAgeCalendarDays": latest_age_days,
        "current365DayCoverageCandidate": current_depth_candidate,
        "candidateWeekdayGapCount": len(gaps),
        "candidateWeekdayGapDatesFirst20": gaps[:20],
        "adjustedCloseMissingCount": missing_adjusted,
        "dividendEventRows": dividend_events, "splitEventRows": split_events,
        "sourceProvidersDeclared": sorted(providers),
        "historicalPointInTimeEligible": False,
        "independentProviderReconciliationVerified": False,
        "productionCoverageClaimed": False,
        "continuityVerified": False,
    }


def audit_journey(fetch, *, symbol: str, now: datetime) -> dict:
    """Audit responses through injected GET(path, params); no fixture fallback."""
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol):
        raise AuditBlocked("Invalid symbol")
    if now.tzinfo is None or now.utcoffset() is None:
        raise AuditBlocked("Audit clock must be timezone-aware")
    now = now.astimezone(timezone.utc)

    quote = _object(_object(fetch("/api/v1/market/quote", {"symbol": symbol})).get("data"))
    if _text(quote.get("symbol")).upper() != symbol:
        raise AuditBlocked("Quote identity mismatch")
    price = quote.get("close")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise AuditBlocked("No usable market price")
    provider = _text(quote.get("sourceProvider"))
    if not provider:
        raise AuditBlocked("Quote provenance missing")
    retrieved = _timestamp(quote.get("retrievedAt"), now=now)
    observed = _timestamp(quote.get("timestamp"), now=now)
    if observed > retrieved + timedelta(minutes=5):
        raise AuditBlocked("Quote observation exceeds retrieval")
    mode = quote.get("quoteMode")
    if mode not in ("provider_fast_info", "historical_daily_close_fallback"):
        raise AuditBlocked("Unknown quote mode")
    if mode == "historical_daily_close_fallback" and not _text(quote.get("priceSessionDate")):
        raise AuditBlocked("Daily close has no session date")
    if quote.get("realTimePriceVerified") is not False or quote.get("historicalPointInTimeEligible") is not False:
        raise AuditBlocked("Quote claims unsupported market authority")
    identity_status = quote.get("canonicalIdentityStatus", "unresolved")
    instrument_id = quote.get("instrumentId")
    if identity_status == "matched_internal_listing":
        if type(instrument_id) is not int or instrument_id <= 0:
            raise AuditBlocked("Invalid matched internal identity")
    elif identity_status not in (None, "unresolved") or instrument_id is not None:
        raise AuditBlocked("Unresolved quote claims internal identity")

    history = _history_audit(fetch, symbol=symbol, now=now)

    query = f'"{symbol}" stock earnings'
    news = _object(fetch("/api/v1/news/feed", {"query": query, "limit": "5"}))
    if news.get("query") != query or news.get("advisoryStatus") != "no_advice" or news.get("productionEligible") is not False:
        raise AuditBlocked("News query or authority mismatch")
    policy = _object(news.get("policy"))
    if policy.get("automaticTrading") is not False or policy.get("athenaRecommendationInfluence") is not False:
        raise AuditBlocked("News authority escalation")
    if not _text(news.get("sourceProvider")):
        raise AuditBlocked("News provenance missing")
    news_retrieved = _timestamp(news.get("retrievedAt"), now=now)
    items = news.get("items")
    if not isinstance(items, list):
        raise AuditBlocked("News items missing")
    newest_published = None
    for item in items:
        article = _object(item)
        if (not _text(article.get("publisher"))
                or _text(article.get("sourceProvider")) != _text(news.get("sourceProvider"))
                or not _https_article_url(article.get("articleUrl"))):
            raise AuditBlocked("News article provenance missing or invalid")
        published = _timestamp(article.get("publishedAt"), now=now)
        article_retrieved = _timestamp(article.get("retrievedAt"), now=now)
        if published > article_retrieved + timedelta(minutes=5) or article_retrieved > news_retrieved + timedelta(minutes=5):
            raise AuditBlocked("News article temporal provenance mismatch")
        if newest_published is None or published > newest_published:
            newest_published = published

    params = {"symbol": symbol}
    if instrument_id is not None:
        params["instrumentId"] = str(instrument_id)
    dossier = _object(_object(fetch("/api/v1/recommendations/production/professional-dossier", params)).get("data"))
    if _text(dossier.get("symbol")).upper() != symbol:
        raise AuditBlocked("Dossier symbol mismatch")
    if instrument_id is not None and dossier.get("instrumentId") != instrument_id:
        raise AuditBlocked("Dossier instrument mismatch")
    if (dossier.get("advisoryStatus") != "no_advice"
            or dossier.get("readOnly") is not True
            or any(dossier.get(flag) is not False for flag in (
                "productionEligible", "allocationEligible", "executionEligible",
                "orderRoutingEligible", "automaticTrading"))):
        raise AuditBlocked("Dossier authority escalation")
    as_of = _timestamp(dossier.get("asOf"), now=now)
    modules = _object(dossier.get("professionalModules"))
    if set(modules) != MODULES:
        raise AuditBlocked("Dossier modules incomplete")
    attached = []
    missing = []
    for name in sorted(MODULES):
        module = _object(modules[name])
        if (module.get("productionEligible") is not False
                or module.get("recommendationInfluence", False) is not False
                or module.get("automaticTrading", False) is not False):
            raise AuditBlocked("Dossier module authority escalation")
        (attached if module.get("evidence") is not None else missing).append(name)

    return {
        "status": ("stale_research_evidence" if (now - retrieved > timedelta(hours=24) or now - observed > timedelta(hours=24) or now - news_retrieved > timedelta(hours=24) or (newest_published is not None and now - newest_published > timedelta(days=7)) or now - as_of > timedelta(hours=24) or (history["latestObservationAgeCalendarDays"] is not None and history["latestObservationAgeCalendarDays"] > 7))
                   else "partial_research_evidence" if (attached and items and history["current365DayCoverageCandidate"]) else "incomplete_evidence"),
        "symbol": symbol,
        "auditClockUtc": now.isoformat(),
        "quote": {"providerDeclared": provider, "mode": mode,
                  "retrievedAt": retrieved.isoformat(),
                  "observedAt": observed.isoformat(),
                  "observationAgeHours": round((now - observed).total_seconds() / 3600, 2),
                  "observationStaleOver24Hours": now - observed > timedelta(hours=24),
                  "ageHours": round((now - retrieved).total_seconds() / 3600, 2),
                  "staleOver24Hours": now - retrieved > timedelta(hours=24),
                  "internalIdentityMatched": instrument_id is not None,
                  "realTimeVerified": False, "historicalPitEligible": False},
        "history": history,
        "news": {"providerDeclared": news["sourceProvider"], "items": len(items),
                 "retrievedAt": news_retrieved.isoformat(),
                 "newestPublishedAt": newest_published.isoformat() if newest_published else None,
                 "feedStaleOver24Hours": now - news_retrieved > timedelta(hours=24),
                 "newestArticleAgeHours": round((now - newest_published).total_seconds() / 3600, 2) if newest_published else None,
                 "newestArticleStaleOver7Days": now - newest_published > timedelta(days=7) if newest_published else None,
                 "issuerIdentityIndependentlyVerified": False},
        "dossier": {"pitAsOf": as_of.isoformat(),
                    "ageHours": round((now - as_of).total_seconds() / 3600, 2),
                    "staleOver24Hours": now - as_of > timedelta(hours=24),
                    "evidenceAttachedCount": len(attached),
                    "moduleCount": len(MODULES), "modulesWithEvidence": attached,
                    "modulesWithoutEvidence": missing,
                    "externalIdentityIndependentlyVerified": False},
        "limitations": ["Provider claims and licensing are not independently attested.",
                        "History was retrieved now; 365-day depth is not independently validated continuity or PIT.",
                        "Weekday gaps include exchange holidays and UTC session-date approximation.",
                        "Attached evidence is not independent PIT validation.",
                        "News article recency uses a seven-day audit threshold, not a market-session or issuer-identity validation.",
                        "No Ollama execution, predictive accuracy or deployment is verified."],
        "completeResearchVerified": False,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def make_fetch(origin: str):
    parsed = urlsplit(origin)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"))):
        raise AuditBlocked("Use an HTTPS backend origin or loopback HTTP")
    try:
        _ = parsed.port
    except ValueError:
        raise AuditBlocked("Invalid backend origin") from None
    opener = build_opener(_NoRedirect())

    def fetch(path: str, params: dict[str, str]) -> dict:
        request = Request(origin.rstrip("/") + path + "?" + urlencode(params),
                          headers={"Accept": "application/json", "Cache-Control": "no-cache"})
        try:
            with opener.open(request, timeout=15) as response:
                if response.status != 200 or "application/json" not in response.headers.get("Content-Type", "").lower():
                    raise AuditBlocked("Live endpoint unavailable")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise AuditBlocked("Response too large")
                return _object(json.loads(raw))
        except AuditBlocked:
            raise
        except Exception:
            raise AuditBlocked("Live endpoint unavailable or invalid JSON") from None

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-origin", required=True)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_journey(make_fetch(args.backend_origin), symbol=args.symbol,
                               now=datetime.now(timezone.utc))
    except AuditBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    # An incomplete or merely partial research chain must not pass a release gate.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

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


def audit_journey(fetch, *, symbol: str, now: datetime) -> dict:
    """Audit responses through injected GET(path, params); no fixture fallback."""
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\\-]{0,19}", symbol):
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
    for item in items:
        article = _object(item)
        if not _text(article.get("publisher")) or not _text(article.get("sourceProvider")):
            raise AuditBlocked("News article provenance missing")
        _timestamp(article.get("publishedAt"), now=now)
        _timestamp(article.get("retrievedAt"), now=now)

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
        "status": "evidence_present" if attached and items else "incomplete_evidence",
        "symbol": symbol,
        "auditClockUtc": now.isoformat(),
        "quote": {"providerDeclared": provider, "mode": mode,
                  "retrievedAt": retrieved.isoformat(),
                  "ageHours": round((now - retrieved).total_seconds() / 3600, 2),
                  "internalIdentityMatched": instrument_id is not None,
                  "realTimeVerified": False, "historicalPitEligible": False},
        "news": {"providerDeclared": news["sourceProvider"], "items": len(items),
                 "retrievedAt": news_retrieved.isoformat(),
                 "issuerIdentityIndependentlyVerified": False},
        "dossier": {"pitAsOf": as_of.isoformat(), "evidenceAttachedCount": len(attached),
                    "moduleCount": len(MODULES), "modulesWithEvidence": attached,
                    "modulesWithoutEvidence": missing,
                    "externalIdentityIndependentlyVerified": False},
        "limitations": ["Provider claims and licensing are not independently attested.",
                        "Attached evidence is not independent PIT validation.",
                        "No Ollama execution, predictive accuracy or deployment is verified."],
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
    return 0 if report["status"] == "evidence_present" else 2


if __name__ == "__main__":
    raise SystemExit(main())

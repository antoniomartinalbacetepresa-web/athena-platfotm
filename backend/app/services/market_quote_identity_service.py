"""Conservative provider quote to persisted internal listing binding.

An exact internal row match is NOT independent identity verification or PIT evidence.
"""
from __future__ import annotations

from typing import Any
from app.repositories.instrument_repository import InstrumentRepository


class MarketQuoteIdentityService:
    def __init__(self, repository: InstrumentRepository | None = None) -> None:
        self._repository = repository if repository is not None else InstrumentRepository()

    def resolve(self, quote: dict[str, Any]) -> dict[str, object]:
        unresolved: dict[str, object] = {"canonicalIdentityStatus": "unresolved"}
        fields = ("symbol", "exchange", "currency", "sourceProvider", "quoteType")
        if any(not isinstance(quote.get(k), str) or not quote[k].strip() for k in fields):
            return unresolved
        if quote["sourceProvider"].strip().lower() != "yahoo":
            return unresolved
        if quote["quoteType"].strip().upper() != "EQUITY":
            return unresolved
        symbol = quote["symbol"].strip().upper()
        exchange = quote["exchange"].strip().upper()
        currency = quote["currency"].strip().upper()

        # No fuzzy joins or unreviewed provider-exchange alias mappings.
        listing = self._repository.get_by_listing(symbol, exchange)
        if listing is None or listing.get("is_active") != 1:
            return unresolved
        if str(listing.get("symbol") or "").strip().upper() != symbol:
            return unresolved
        if str(listing.get("exchange_short_name") or "").strip().upper() != exchange:
            return unresolved
        if str(listing.get("currency") or "").strip().upper() != currency:
            return unresolved
        if str(listing.get("instrument_type") or "").strip().lower() not in {
            "stock", "equity", "common_stock", "common stock",
        }:
            return unresolved
        instrument_id = listing.get("id")
        if type(instrument_id) is not int or instrument_id <= 0:
            return unresolved
        return {
            "canonicalIdentityStatus": "matched_internal_listing",
            "instrumentId": instrument_id,
        }

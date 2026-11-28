# Market quote temporal provenance and daily fallback

The public `GET /api/v1/market/quote` response retains `data.close`,
`data.timestamp` and `data.retrievedAt`. The two time fields now describe
**when the Yahoo request finished**, not when it started.

`quoteMode=provider_fast_info` denotes a price from Yahoo fast-info, which
may be delayed. `quoteMode=historical_daily_close_fallback` denotes the last
available daily close when no valid positive fast-info price is available.
`priceSessionDate` gives the timezone-aware exchange-local session date of
that fallback bar; it is not an exact execution timestamp.

Both modes explicitly set `realTimePriceVerified=false` and
`historicalPointInTimeEligible=false`. Neither is proof of a live quote,
pre-existing PIT evidence, a reliable historical market event timestamp, or
investment authority. Consumers must display fallback prices as **last
available daily close**, not as live prices.

The fallback rejects missing timezone, a future-dated bar, or nonpositive
prices. A nonpositive previous close cannot generate a misleading change.
This change improves quote provenance but does not demonstrate production
market-data quality or deployed E2E acceptance.

When using a daily-close fallback, open, high, low, volume and the
comparison previous close are taken from that same historical series.
The service must not combine fast-info session values with a fallback
close from a different session.

## Exact internal listing match for research navigation

The quote may carry `canonicalIdentityStatus=matched_internal_listing`
and a positive `instrumentId` only when its Yahoo symbol, exchange code,
currency and equity type exactly match one active internal ATHENA listing.
Unreviewed exchange aliases and symbol-only joins are forbidden.
Otherwise identity remains unresolved and navigation uses only the symbol.

Flutter propagates the matched internal ID into the professional dossier,
which independently checks the echoed symbol and ID and fails closed on
mismatch. A match with an internal database row does not independently
verify a security identifier or authorize PIT usage of the current quote.
Provider data, licensing, coverage and production deployment remain
separate acceptance gates.

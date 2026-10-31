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

# Capital.com — secondary provider evaluation (pending, 2026-11-20)

Status: **candidate only; not authorized for ingestion or production use**. This evaluation does not replace the primary equity-price provider or the future IBKR paper broker.

## Non-negotiable instrument boundary

Capital.com instruments may be CFDs. A CFD quote is **not** a primary-exchange cash-equity trade or official stock close. Never merge CFD bars with spot equity history, use them to fill missing stock candles, or infer stock corporate-action adjustments from CFD pricing. Instrument identity must include provider, provider instrument ID, instrument type, underlying reference (if known), venue, currency, and quote semantics.

## Required evidence before enabling an adapter

- Obtain and archive current API terms and written/contractual permission for the intended Spain-based personal research use, including retrieval, retention, caching, derived analytics, display and redistribution restrictions.
- Confirm API authentication, account requirements, rate limits, costs, REST/WebSocket behavior and historical depth against official documentation; do not assume access or free real-time prices.
- Sample authorized instrument data using a real clock and record observedAt, availableAt, retrievedAt, timezone, currency, quote type, provider license identifier, staleness, missing intervals, and corporate-action treatment.
- Compare like-for-like instrument types against an independent licensed source. Do not label CFD-vs-stock differences as a stock-data quality failure.
- Design any adapter as **read-only by construction**, with an explicit endpoint allowlist excluding position, deal, order and account-mutation operations; no demo/live orders. Keep credentials outside code and do not request them in chat.
- Verify fail-closed behavior for absent permission, unsupported instrument, missing PIT timestamps, unavailable source, stale quotes and incomplete history.
- Add focused backend contract tests and Flutter error/attribution acceptance before operational enablement.

## Decision gate

Do not enable data ingestion or increase acceptance scores until permissions, source identity, tests, exact-SHA CI and real-clock E2E evidence are documented. Until then, prioritize the primary Market → News → ATHENA vertical flow. UX ideas may be assessed independently without copying proprietary assets.

Related acceptance dependencies: CORE-001, CORE-006, PRODUCT-001, PRODUCT-007. No new acceptance percentage is claimed by this note.

# Persisted history -> private canonical research cycle

Dependencies: CORE-001/CORE-002 and PRODUCT-001 in `ACCEPTANCE_INVENTORY.md`.
This increment is synthetic implementation evidence, not operational acceptance.
The real-data licensing/PIT/coverage gates remain open and all order gates false.

## API and integrity contract

Authenticated `POST /api/v1/recommendations/professional-research/research-cycle/from-persisted-market-history`
accepts only an internal instrument ID, symbol, source, observation window,
stable `asOf`/`recordedAt`, journal/revision, human thesis, human references and
contradictory evidence. No client bars, reference hash, licence or production
flags are accepted. Internal IDs/limits are strict integers. Replays use the same
selection and human context; the server does not replace the cutoff with `now`.

The server resolves existing history. Until a trusted rights contract exists,
only sources conservatively marked `synthetic_fixture` can use this bridge;
unverified origins return 409 without writing research. A fixture marker is a
declared-name warning, not an independent attestation of provenance or rights.
No provider calls, account connections or real market-data acquisition occur.

The new append-only table stores **IDs, hashes and metadata only**, not OHLCV.
Row hashes bind a fixed versioned projection of the original persisted row.
The reference is bound into both Radar `data_quality` evidence and a Journal
`assumption` via `urn:athena:market-history:<sha256>`, so the existing canonical
Radar/Journal/Devil's Advocate cycle hash protects the attachment URI. The
requester cannot inject that reserved namespace into any evidence component.
Urgency remains routine research attention, never a buy/sell signal.

History, reference, Journal and Cycle must share one SQLite database. The
reference is checked against the selected row values during capture and checked
again under the same `BEGIN IMMEDIATE` that appends Journal and Cycle. A failed
cycle rolls back all three artifacts. Selection/capture/append races, different
databases with reused row IDs, duplicate IDs and changed journal revisions fail
closed. An unrelated schema column does not invalidate the versioned row hash.

`GET /api/v1/recommendations/professional-research/market-history-reference/private/{hash}`
requires the same authenticated owner. It revalidates reference JSON, identity,
time bounds and underlying row hashes. Private Cycle reads revalidate their
reserved attachments too; a changed/deleted row cannot retain a successful
package-integrity claim. Public or other-owner Cycle reads remain unavailable.
This is tamper-evident application persistence, not WORM or cryptographic source
attestation against an administrator who can rewrite the entire database.

## Reproducible regressions and continuation checkpoint

Entry baseline: `7c6bfae1ac2a2fa50d9c90f0193fbf48fe92db3b`; its push validation
[45989546364](https://github.com/antoniomartinalbacetepresa-web/athena-platfotm/actions/runs/45989546364)
passed backend, Flutter, Chrome, release Web build and release gate. The earlier
`9f7d8c5e8a269e7a7d8c420566e5e8195b038db5` delivery remains the preceding UI baseline.
The final bridge SHA and exact-SHA CI conclusion are recorded by its commit/run
and the execution report; this document does not preclaim a future CI pass.

```sh
cd backend
python -m pytest -q tests/test_persisted_market_research_cycle_api.py \
  tests/test_live_company_news_research_cycle_api.py \
  tests/test_recommendation_professional_research_cycle_persistence.py \
  tests/test_recommendation_professional_research_cycle_external_provenance_api.py
```

All test prices/instruments/feeds are explicitly synthetic. Coverage includes
private retrieval, idempotence, rollback, source/cutoff mismatch, client flags
and attachment spoofing, temporal precision, tampered JSON/rows, capture races
and mismatched databases. Existing news-cycle behavior remains regression-covered.

Queue for the next 24 hours, ordered by dependencies rather than commit quotas:

1. Add authenticated Flutter transport and review flow for this bridge, preserving
   frozen cutoffs and human context; accept loading/error/private retrieval with
   synthetic integration tests before claiming a deployed end-to-end journey.
2. Obtain independent data rights/availability/adjustment/calendar evidence for
   Twelve Data and >=365-day eligible coverage; do not unlock real writes by a
   client flag or a provider name. External provider/owner evidence is still needed.
3. Combine server-bound market, News/Investors references under one canonical
   cycle without presenting delayed reports as live trades or promoting fixtures.
4. Implement and test the versioned 25-prior-session rebound hypothesis with
   OHLCV, explicit costs/invalidation and OOS separation; no profitability claim.
5. Preserve disabled execution/broker scope and the official review in
   `docs/providers/BROKER_OFFICIAL_REVIEW_20261127.md`. Keep the existing hourly
   automation intact; a manual Work commit does not certify its environment binding.

Current global acceptance remains **not certifiable**. No canonical requirement,
historical feature, production gate or target date is removed by this increment.

# Local persisted history -> API -> Flutter transport

Scope: implementation evidence toward CORE-001, CORE-002 and PRODUCT-001.
Operational acceptance remains pending. Canonical plans and hourly contract
are unchanged.

`GET /api/v1/market/history/persisted` selects an internal `instrumentId`, an
explicit `sourceProvider`, aware `observedFrom`, `observedTo` and `asOf`, and
`limit` (1–400). The window is at most 366 days. The service reads a single
SQLite snapshot, never calls a provider and never writes market observations.
It returns the most recent selected observations in ascending order, with an
explicit truncation flag. It does not substitute another source on absence.

Each row retains observation ID, OHLCV, source, observation/retrieval/source
timestamps and the internal listing ID. Local availability is conservatively
the persisted retrieval instant; it is never fabricated historical publication
time. Cutoffs are checked at microsecond precision after SQLite prefiltering.
Catalogue identity is explicitly current metadata, not historical identity.
Unknown instruments return 404; storage failures return sanitized 503 rather
than a successful empty history. Twelve Data previews remain refused by the
shared source policy pending rights and PIT evidence.

The Flutter backend provider has an explicit `getPersistedHistoricalData`
method. It retains immutable observations and truncation metadata, checks the
requested listing/source/window and refuses future retrieval, authority
escalation, duplicate IDs and non-monotonic observations. HTTP errors never
fall back to current provider history. Existing current-history behavior is
preserved. This increment supplies transport, not a completed screen workflow.

Synthetic regression commands:

```sh
cd backend
python -m pytest -q tests/test_persisted_market_history_api.py \
  tests/test_twelve_data_history_service.py tests/test_market_observation_repository.py
cd ../app
flutter test test/features/market/persisted_market_history_test.dart \
  test/features/market/athena_backend_market_data_provider_test.dart
```

Backend fixtures demonstrate idempotent writes followed by a new service/API
read, source isolation and honest errors. Flutter fixtures exercise the same
JSON shape using a mocked HTTP transport. They do not establish a deployed
end-to-end journey or rights to real data. `licenceVerified`, production
coverage, historical PIT eligibility and order authority remain false.

## Selected-instrument surface increment

Market now offers `VER HISTÓRICO GUARDADO` after a traceable quote with an
internal listing ID. It opens `PersistedMarketHistoryPanel` with the exact
symbol, listing, declared source and currency. Loading is explicit and uses
the existing backend transport; no current-provider fallback is introduced.
The panel displays local knowledge cutoff, row IDs/timestamps, close, currency,
volume and truncation, with distinct loading/empty/error/retry states. Refresh
clears the old prices immediately and selection changes invalidate late results.

Tests added: `app/test/features/market/persisted_market_history_panel_test.dart`
exercises the HTTP transport's synthetic schema through the widget and failure,
retry, currency and late-response handling. The existing
`market_professional_research_entry_test.dart` exercises the Market dialog,
exact selection and invalidation when the symbol changes. Test execution and
exact-SHA CI are recorded separately; fixtures are not deployment acceptance.

## Synthetic evidence classification

The API now includes `evidenceKind` on each row and its provenance envelope.
The only values are `synthetic_fixture` and `unverified`. Declared source names
containing explicit tokens `synthetic`, `fixture`, `mock` or `simulated`
(case-insensitive, after bounded URL/HTML decoding) trigger the fixture warning.
The envelope states
`evidenceClassificationBasis=declared_source_name_not_independent_attestation`.
This is a conservative presentation classification: a name cannot authenticate
origin, certify real prices, establish a licence or upgrade PIT eligibility.
Unknown and legacy sources remain readable as unverified; names such as
`real_verified_licensed` confer no authority. No migration or data mutation is
introduced. Existing false licence/PIT/production/order flags remain false.

Flutter preserves this classification in `PersistedMarketEvidenceKind` and
rejects unsupported classifications such as `real` or `licensed`. Missing legacy
metadata defaults to unverified; explicit synthetic row/envelope labels or
recognizable fixture source names produce a visible, accessible
`DATOS SINTÉTICOS DE PRUEBA` warning. That warning also survives an empty
synthetic-source result. Unknown-source results explicitly state that their
origin is not verified, rather than implying authentic market operation.
Injected test loaders cannot suppress the warning merely by omitting the new
field when the selected source or returned points already identify fixtures.

Regressions in the existing dedicated API, transport and panel test files cover
fixture/encoded-source labels, unknown legacy sources, unsupported authority
claims and the visible distinction between synthetic and unverified history.

Next: obtain separate provider licensing/availability and deployed integration
evidence, then bind accepted history to the canonical research cycle. The scope
audit/next queue is in `master_scope_traceability_20261127.md`. A manual Work
commit does not prove hourly automation/environment binding.

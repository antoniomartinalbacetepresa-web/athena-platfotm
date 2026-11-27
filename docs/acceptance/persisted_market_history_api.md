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

Next: connect this explicit replay transport to the selected-instrument history
surface, validate its loading/empty/truncated/error states, and obtain separate
provider licensing/availability and deployed integration evidence. A manual
Work commit does not prove hourly automation/environment binding.

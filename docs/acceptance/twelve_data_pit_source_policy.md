# Twelve Data preview provenance at the PIT boundary

Acceptance dependency: CORE-001. This increment closes a synthetic regression,
not licensed real-data acceptance or measured 365-day coverage.

The daily preview adapter still returns `historicalPointInTimeEligible=false`.
Its provider identity must also be rejected independently of that flag, including
when a caller relabels the batch or imports records directly into SQLite.

The common source validator now applies the existing Twelve Data storage refusal
after URL/HTML decoding and punctuation/case normalization. Repository writes,
repository reads, backfill preflight and PIT outcome/benchmark price selection
share this validator. Per-row `sourceProvider` metadata is checked as well as
the batch provider. A rejected row rolls back the batch. Imported preview rows
are excluded on read without deleting historical records, and cannot displace
an eligible synthetic control price at the same observation time.

Regression: `backend/tests/test_twelve_data_pit_source_policy.py`. All prices,
instruments and databases in this regression are explicitly synthetic. Before
the fix, 12 of its 15 cases failed; the other three covered existing behavior.
With the fix, all 15 pass. The combined focused suite has 124 passing tests:

```sh
cd backend
python -m pytest -q tests/test_twelve_data_pit_source_policy.py \
  tests/test_twelve_data_history_service.py \
  tests/test_market_pit_price_source_provenance.py \
  tests/test_market_history.py tests/test_market_observation_backfill_service.py
```

Cloud execution baseline: Python 3.12.14 and the repository's backend
requirements in an isolated virtual environment; starting branch SHA
`9419d95a4710cd952a1b32a5e16a9342d3a3aa37`. Synthetic tests run with inherited
HTTP/SOCKS proxy variables unset to avoid requiring optional SOCKS transport at
application import. This is a test-process setting, not an application change.
Exact final SHA and local/global CI results belong in the execution report.

Remaining: documented provider usage/storage rights, historical availability
policy, real coverage and independent corporate-action reconciliation. No real
provider requests or broker connections are needed for this regression. Next
step: implement and test the licensed provenance-to-persistence bridge only
after its rights and availability contract is established; continue synthetic
integration while that evidence is pending.

# Corporate-action reconciliation: complete operational export

This runbook produces a **complete PIT worklist** of unresolved dividends and splits (missing independent provider evidence, incomplete units, unclassified provenance, or conflicting economic values). It does **not** establish 365-day price-history coverage, canonical agreement, production readiness, or permission to trade.

## Authorized execution

Run from the backend environment with read access to an **authorized operational SQLite database or previously captured consistent snapshot** and write access to a private output directory:

```text
python -m scripts.export_corporate_action_reconciliation --database <AUTHORIZED_DB_OR_SNAPSHOT> --output <NEW_PRIVATE_OUTPUT.jsonl> --as-of 2026-10-28T12:00:00+00:00
```

The command opens the source SQLite database in **read-only** mode, uses SQLite's online backup API to obtain a transactionally consistent local copy (including committed WAL changes), checks its integrity, and runs the existing PIT reconciliation service only on that copy. The source is not initialized, migrated, or written to. The local copy is removed when the export finishes.

The output is newline-delimited JSON: one metadata record followed by **every** unresolved economic event. Metadata contains the fixed UTC cutoff, snapshot SHA-256, incomplete/conflict totals, and explicit no-production/no-canonicalization flags. The command checks that the number of exported events equals the diagnostic totals and that economic event identities are unique. The output is created with restricted permissions and published exclusively: an existing report is never overwritten. A successful command prints an output SHA-256 for custody/audit. Preserve the authorized source snapshot and report in a protected evidence store if independent reproduction is required.

**Do not** run this with a fixture and label the result operational. Do not commit operational databases, reports, instrument-level sensitive holdings, secrets, or environment credentials. Run on a secured host with appropriate disk space. The exporter processes fixed-size pages from the same consistent snapshot, validates the total and ordering of every page, and writes JSONL incrementally without retaining the entire unresolved-event list. The service still scans the eligible universe on each page, so very large exports can be CPU/IO intensive; benchmark and schedule them off-peak rather than treating paging as a throughput guarantee. A future PIT cutoff is rejected. Failed or inconsistent exports are not published.

## Acceptance boundary

The operator must separately establish the source's operational origin, eligibility-universe definition, acquisition time, access authorization, and custody. The exporter verifies SQLite snapshot consistency, **not** that the database is a genuine production source or that provider families are contractually independent. Conflicting events require independent review; the tool neither chooses a winning source nor performs backfill. Only an operator-verified full-universe historical diagnostic, independent reconciliation, and separately approved release gates can close production criteria.


## Bounded secondary-provider sweep (authorized writes)

After reviewing the complete worklist, an authorized operator may request a bounded
Alpha Vantage secondary backfill (requires provider configuration and approval):

```text
python -m scripts.backfill_verified_secondary_corporate_actions --sweep --limit 10 --max-batches 20 --as-of 2026-10-30T00:00:00+00:00
```

Unlike repeated calls with an increasing `--offset` against a shrinking live
queue, `--sweep` freezes actionable incomplete events from one consistent
SQLite backup, groups them by instrument, and processes each selected instrument
at most once. It retains the frozen listing identity (including exchange, type,
issuer, financial identifier and currency) and refuses a changed identity before
fetching the next batch. It reports actionable events not attempted because of
the explicit batch cap; a partial sweep is not success for the full universe.

The operator must separately verify the database's operational origin, provider
license, rate limits and actual economic agreement. A second configured provider
does not by itself prove independence; conflicts remain unresolved and are never
canonicalized automatically. No fixture, successful command, or green CI
constitutes production evidence. Do not automatically loop on increasing offsets.

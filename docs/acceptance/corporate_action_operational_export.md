# Corporate-action reconciliation: complete operational export

This runbook produces a **complete PIT worklist** of unresolved dividends and splits (missing independent provider evidence, incomplete units, unclassified provenance, or conflicting economic values). It does **not** establish 365-day price-history coverage, canonical agreement, production readiness, or permission to trade.

## Authorized execution

Run from the backend environment with read access to an **authorized operational SQLite database or previously captured consistent snapshot** and write access to a private output directory:

```text
python -m scripts.export_corporate_action_reconciliation --database <AUTHORIZED_DB_OR_SNAPSHOT> --output <NEW_PRIVATE_OUTPUT.jsonl> --as-of 2026-10-28T12:00:00+00:00
```

The command opens the source SQLite database in **read-only** mode, uses SQLite's online backup API to obtain a transactionally consistent local copy (including committed WAL changes), checks its integrity, and runs the existing PIT reconciliation service only on that copy. The source is not initialized, migrated, or written to. The local copy is removed when the export finishes.

The output is newline-delimited JSON: one metadata record followed by **every** unresolved economic event. Metadata contains the fixed UTC cutoff, snapshot SHA-256, incomplete/conflict totals, and explicit no-production/no-canonicalization flags. The command checks that the number of exported events equals the diagnostic totals and that economic event identities are unique. The output is created with restricted permissions and published exclusively: an existing report is never overwritten. A successful command prints an output SHA-256 for custody/audit. Preserve the authorized source snapshot and report in a protected evidence store if independent reproduction is required.

**Do not** run this with a fixture and label the result operational. Do not commit operational databases, reports, instrument-level sensitive holdings, secrets, or environment credentials. Run on a secured host with appropriate disk space: the current reconciliation service materializes the worklist in memory; this exporter intentionally fails rather than silently truncating it. Very large universes will require a separately reviewed streaming implementation.

## Acceptance boundary

The operator must separately establish the source's operational origin, eligibility-universe definition, acquisition time, access authorization, and custody. The exporter verifies SQLite snapshot consistency, **not** that the database is a genuine production source or that provider families are contractually independent. Conflicting events require independent review; the tool neither chooses a winning source nor performs backfill. Only an operator-verified full-universe historical diagnostic, independent reconciliation, and separately approved release gates can close production criteria.

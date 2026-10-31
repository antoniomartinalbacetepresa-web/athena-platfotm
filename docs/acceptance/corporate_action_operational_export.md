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
queue, `--sweep` freezes actionable unresolved events suggested for Alpha Vantage from one consistent
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

The sweep command exits with status **3** if the bounded selection leaves actionable
events unattempted or an instrument fails; an incomplete run cannot be treated
as successful by an unattended scheduler. Conflicting economic evidence remains
a review item even after a secondary observation is collected.

## PIT-bounded secondary retrieval

The secondary corporate-action backfill accepts only strict `YYYY-MM-DD`
`--from-date` and `--to-date` values. An explicit `--to-date` later
than the UTC `--as-of` date is rejected before provider retrieval; a
`--from-date` without `--to-date` is automatically capped at the UTC
`--as-of` date rather than allowing an unbounded provider request. A
reversed or malformed date window fails closed for both single-batch and
`--sweep` execution.

The Alpha Vantage adapter filters its own date range, but the secondary
backfill now **independently validates every returned observation** against
the requested UTC date window before ingestion. An invalid timestamp or
out-of-window row rejects that instrument's entire response, including
otherwise valid actions in the same response; no partial write is made
from that response. The operator must investigate provider discrepancies
rather than silently trimming them. These safeguards do not establish
operational provider independence, successful economic reconciliation, or
historical price-coverage readiness.



## General corporate-action ingestion and CLI exit contract

The shared `CorporateActionIngestionService` now validates **every** returned
observation, including rows without dividends or splits, before writing any
batch. It checks strict `YYYY-MM-DD` request bounds, UTC-normalized economic
dates, timezone-aware effective/retrieval instants, chronological consistency,
and rejects future effective or retrieval timestamps. If a lower bound is
specified without an upper bound, the request is capped to the current UTC
date. Any invalid or out-of-window observation rejects that instrument's
whole response without partial persistence. A UTC-day boundary may differ
from an exchange-local trading day; operators must investigate those cases,
not silently discard the discrepancy.

The basic `backfill_secondary_corporate_actions` command exits **3** when any
selected instrument fails (and **0** only when its selected batch has no
reported failures). The verified single-batch command exits **3** when a
selected event remains incomplete or conflicting, or when an instrument fails.
The verified sweep retains its bounded-selection contract: it exits **3** for
unattempted actionable events or failed instruments. A zero exit status from
any bounded command is **not** evidence of complete eligible-universe
coverage, independent operational provider agreement, or production readiness.

Provider-supplied historical `retrievedAt` is **never** treated as proof
of ATHENA's own acquisition time during shared-history ingestion. New actions
are stored with the locally observed UTC response receipt time, after complete
response validation. The new `capture_verified=1` marker distinguishes those
rows from pre-existing rows (`capture_verified=0` after additive migration).
A replay with the same provider, economic identity and source timestamp is
idempotent across separate local captures **only** when a previously captured
row has that marker. A different dividend amount, split ratio, currency or
source timestamp remains a distinct immutable observation; no automatic
canonicalization or investment authority follows.

**Legacy PIT warning:** this additive migration does not rewrite or erase
older provider-declared `retrieved_at` values. Legacy rows are marked
unverified but existing readers can still see them. Consequently, historical
PIT/OOS/total-return evidence derived from legacy corporate actions remains
unfit for operational acceptance until a separately approved, audited
quarantine/backfill or explicit verified-capture filter is applied across
every downstream reader. A green CI cannot repair historical provenance.
Only separately audited acquisition logs and independent source custody can
close that provenance criterion.


## Immutable PIT event identity and provenance replay

Schema v6+ deliberately permits **multiple distinct economic events** from the
same provider at the same effective and retrieval instants. The immutable
identity includes the economic payload (`event_identity`: type, cash amount,
split ratio and currency), not just the date and provider. A replay is
idempotent when that entire identity and its source timestamp match. A replay
of the **same economic event** with a different `source_timestamp` fails
closed, rather than silently discarding the contradictory provenance. The
repository rolls back the entire `save_many` transaction on such a conflict;
SQLite CHECK/foreign-key violations are not masked by blanket
`INSERT OR IGNORE`.

Different economic amounts at the same effective instant are **not**
automatically labelled corruption or merged: they may represent separate
legitimate distributions, and the reconciliation layer must evaluate their
meaning independently. A later retrieval instant can also preserve a revised
observation without rewriting older PIT evidence.

The shared ingestion path now groups a validated response by provider and
uses one local receipt timestamp for all its actions. Each provider batch is
transactional; **different provider batches are not one transaction**.
A prior committed provider batch may remain if a later provider batch fails.
The operator must inspect and reconcile the persisted observations rather
than certify the entire instrument as accepted. Regression evidence here
uses fixtures, not an operational provider, and does not close independent
reconciliation or production gates.

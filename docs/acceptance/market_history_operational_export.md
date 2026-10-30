# Operational PIT market-history gap export

This tool is for an **authorized ATHENA operational SQLite database**, not
fixtures or a synthetic CI database. It creates an online SQLite snapshot in
a temporary directory, includes committed WAL data, runs the existing
365-day/100%-eligible-universe coverage and gap diagnostics against the
**same** snapshot, and publishes a complete JSONL report without overwriting
another operator's evidence.

From the `backend` directory, in an authorized environment:

```bash
python -m scripts.export_market_history_gaps \
  --database /secure/athena/operational.db \
  --output /secure/evidence/history-gaps-20261028.jsonl \
  --as-of 2026-10-28T14:00:00+00:00
```

The output directory must already exist and be appropriately access
controlled. Use a fixed UTC cutoff **not later than execution time**.
Do not put credentials or personal account data in arguments, logs or the
export destination. The source database is opened read-only and is not
changed. The tool does not fetch data, backfill, adjust prices, select a
provider, authorize model learning or execute trades.

The first JSONL record is metadata with the source snapshot SHA-256,
cutoff, eligible instrument count, current deep-history count, blocker
count, per-reason totals, the full aggregate coverage diagnostic and
explicit non-production-claim flags. Subsequent records enumerate **all**
blocking instruments in the stable reason/symbol/id order. The exporter
paginates, reconciles every page and reason total, checks uniqueness, and
requires `currentDeepHistoryInstrumentCount + totalBlockingCount ==
eligibleInstrumentCount`. It fails without publishing a partial file if
the two independent diagnostics disagree or any page is inconsistent.
The command's final JSON contains the export SHA-256 for retention and
independent verification. The snapshot is deleted after execution.

**Acceptance is not achieved by running the tool on fixtures or by green
CI.** An operator must record the database origin, snapshot custody,
actual eligible-universe membership, fixed PIT cutoff, SHA-256 values,
all gap records and any source/provider limitations. The current
eligible universe is the active instrument catalogue, not a historical
point-in-time reconstruction of catalogue membership. A zero-blocker
result on an empty eligible universe is not ready. The 365-day rule is
a minimum current continuous segment from a single permitted source,
not a claim of complete price history since listing or verified
corporate-action adjustments.

For operational closure, independently reconcile dividend/split events
using `scripts.export_corporate_action_reconciliation` against an
authorized snapshot from the same database generation and cutoff.
Execute a separately approved bounded backfill/sweep with free
permitted providers, then re-run both exports and compare their hashes
and unresolved counts. Do not use FMP, mix provider families to manufacture
continuous depth, or promote a model without human approval.

A deployment URL, two disposable staging accounts in protected secrets,
real longitudinal OOS maturities, off-site backup/restore evidence, SMTP
delivery and required protected-branch checks remain separate release
criteria. This tool does not close them.

## Safe bounded backfill after gap review

The authorized `python -m scripts.backfill_deep_market_history --sweep --limit 25 --max-batches 20`
command freezes the blocking worklist from one consistent SQLite generation.
The sweep now also freezes the **full listing identity** (symbol, exchange,
instrument type, issuer/instrument IDs, currency and active status). If the
live catalogue changes any of these fields before a later batch, the sweep
stops **before fetching or persisting that listing**, rather than silently
attaching historical observations to a different security sharing a ticker.
Run this only against a separately authorized writable operational database,
after reviewing the full gap export and a rollback/backup plan. A partial
sweep, a provider error or a changing universe is not 365-day acceptance.

## Price-bearing historical acceptance

The 365-day coverage and gap diagnostics count only PIT-valid observations
with a **numeric, strictly positive, finite closing price**. Timestamp-only,
volume-only, missing-close and invalid legacy-price records do not establish
price history. A missing or corrupt price can split a continuous source
segment and therefore re-open the seven-day gap criterion. Both diagnostics
apply the same predicate so the full eligible-universe blocker reconciliation
remains fail-closed. This is a stricter evidence filter, not a migration,
automatic historical correction or deletion of immutable observations.
An operator must review any resulting gaps and authorize a separately
provenanced backfill or independent source; never overwrite the first
point-in-time observation or infer adjusted-price quality from this check.

## Provider-response PIT boundary for market-history backfill

The bounded Yahoo market-history backfill now validates every returned
observation against the requested UTC date interval before any row for that
instrument is persisted. A provider response that mixes valid rows with
out-of-window rows, omits timezone information, or declares contradictory
`observed_at` and `timestamp` aliases fails closed for that instrument.
An explicit `--from-date` without `--to-date` is bounded to the current
UTC day rather than making an open-ended provider request. The repository
continues to enforce that retrieval knowledge time cannot precede the
observation instant; a response with no explicit date window is still
bounded by the current UTC day and the write-time PIT invariant.

This prevents accidental ingestion outside an approved historical interval,
but does not prove that Yahoo data are complete or independently corroborated.
The comparison uses UTC observation dates; providers whose session date
differs from UTC must supply an appropriately normalized requested window
or be reviewed rather than silently widening the PIT gate. No existing
immutable observation is rewritten, no readiness is automatically promoted,
and no trading or weighting authority is introduced.


## Operational CLI exit status (fail-closed)

The bounded `scripts.backfill_deep_market_history` command exits **0 only if**
the post-write verification satisfies the complete, non-empty eligible-universe
current >=365-day criterion. A successful partial batch with unresolved
instruments exits **3**, as do failed/empty-provider batches that leave the
criterion blocked. The `--sweep` path follows the same readiness rule. Exit 3
means **not ready**, not necessarily that the process crashed or that no rows
were saved; inspect the JSON report and preserve its evidence before deciding
which bounded batch to authorize next.

The general `scripts.backfill_market_observations` command exits **3** when
any selected instrument failed or returned no history, and **0** only when its
selected batch had neither condition. Its exit 0 **does not** mean 365-day
coverage, source independence, corporate-action reconciliation or release
readiness. Both commands preserve their JSON reports on stdout. No command
changes the immutable PIT overwrite policy, approves provider data, or
promotes production readiness automatically.


## Same-day PIT cutoff for live backfill

The verified history backfill now measures its initial blockers at the actual
UTC instant, not the end of the current calendar day. Its post-ingestion
measurement takes a fresh UTC instant so observations retrieved during the
batch can count, while future-dated imported knowledge cannot. The frozen
sweep worklist and the direct blocker-only selection use the same bounded
cutoff. For historical dates already past, the requested day's end remains
the cutoff. This is a code-level no-lookahead safeguard, not proof of live
365-day coverage, production origin or independent corporate-action agreement.

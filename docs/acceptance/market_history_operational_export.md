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

# Paired operational history and corporate-action evidence

Run only on an authorized operational SQLite database on a secured host with a private, existing output directory. From backend:

~~~bash
PYTHONPATH=. python -m scripts.export_operational_history_bundle \
  --database /secure/athena/operational.db \
  --output /secure/evidence/athena-history-actions-20261029.zip \
  --as-of 2026-10-29T10:00:00+00:00
~~~

The command takes **one** online SQLite backup (including committed WAL data), then runs both existing full-universe exporters against descendants of the **same frozen generation and PIT cutoff**. A concurrent write to the live database cannot make the history and dividend/split reports use different universes. The source is opened read-only and is not migrated. The generation SHA-256 is rechecked before publication; each child exporter independently verifies its own snapshot.

The ZIP contains market_history_gaps.jsonl, corporate_action_reconciliation.jsonl and manifest.json. The manifest records generation identity, both child hashes and counts, and explicitly false authority flags. Publication is atomic and exclusive: a failed second export cannot publish the first report, and existing evidence is never overwritten. The final bundle SHA-256 is printed for protected custody and independent audit. The ZIP deliberately excludes the database and secrets; its instrument-level data may still be sensitive.

**Green CI uses fixtures, not operational evidence.** This tool cannot attest operational origin, historical PIT catalogue membership, 365-day/100% coverage, independent provider licensing/agreement or price adjustment quality. An operator must retain authorized source provenance, custody, exact eligible universe, cutoff, the full paired export, independently verified secondary source, approved bounded backfill/sweep and a later paired measurement of remaining gaps and conflicts. No automatic backfill, canonicalization, learning promotion, weighting or trading is performed.

# Research synthesis: offline inventory and real-data activation

This runbook covers the observed local condition in which `GET .../athena-synthesis/latest`
returns `404: No existe ninguna ATHENA synthesis persistida` and
`GET .../news-synthesis/latest` returns `404: No existe ninguna síntesis News persistida`,
while `/api/v1/news/feed` responds `200`. A live RSS feed is **not** a persisted,
verified PIT synthesis; neither 404 proves the corresponding route is absent.

## First: inspect an authorized, consistent SQLite snapshot (no writes)

Use the existing verified-backup/export procedure to obtain a **checkpointed,
consistent copy** of the operational SQLite database, preferably with an
independently recorded SHA-256. Do not copy the live `.db` file while WAL
transactions are active or point this tool at the live database. The auditor
opens its input using SQLite `mode=ro&immutable=1` and never initializes a
repository, migrates schema, executes research or calls an LLM.

From `backend`:

```powershell
.\.venv\Scripts\python.exe scripts\audit_research_synthesis_snapshot.py `
  --snapshot "D:\secure-snapshots\athena-consistent.db" `
  --expected-sha256 "<SHA-256 FROM TRUSTED BACKUP MANIFEST>"
```

`--expected-sha256` is optional for inventory but strongly recommended for
custody; omitting it never implies the snapshot is verified. The output
contains only record counts, content hashes, dependency categories, structural
errors and actionable blockers. Exit `0` means inventory completed, **not**
production readiness; `2` means snapshot/hash/read error; `3` means a
structural/hash mismatch. A structurally complete inventory still requires
canonical HTTP validation and independent model/source provenance. Never use
this report as an authorization to trade, weight, train or promote a model.

## Second: revalidate one persisted cycle canonically (no model calls)

The inventory above intentionally checks structure only. For an existing real
`cycleHash`, run the stricter **read-only** verifier against the same
checkpointed snapshot and the SHA-256 recorded in its trusted backup manifest:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\verify_persisted_research_cycle_snapshot.py `
  --snapshot "D:\\secure-snapshots\\athena-consistent.db" `
  --expected-sha256 "<TRUSTED SNAPSHOT SHA-256>" `
  --cycle-hash "<EXISTING 64-CHAR CYCLE HASH>"
```

This reuses the canonical repository validators for the cycle and required
News/Investors syntheses, checks the News evidence IDs, source references,
availability timestamps and PIT generation interval against the stored Radar,
and derives the **snapshot-local** ATHENA input fingerprint using the same
input-contract algorithm as the backend API. It does not write, migrate, invoke
Ollama, publish research, or authorize investment orders. The verifier also rejects any adjacent SQLite `-wal`, `-shm` or `-journal` file: an immutable reader can otherwise silently ignore committed WAL changes while the main-file SHA-256 still matches. Produce a consistent, closed, checkpointed copy using SQLite backup facilities; never validate a live database or copy only its main file while a writer is active. The expected digest
is mandatory. If an ATHENA synthesis already exists in the snapshot, the
verifier now validates its stored package hash, cycle/Radar/News/Investors
bindings, canonical input fingerprint, evidence/category coverage, PIT
generation time and recomputed output fingerprint. A corrupt existing artifact
**blocks** verification; it is never treated as a valid reason to skip a new
draft. A valid existing artifact yields `athenaAlreadyPersisted=true`,
`persistedAthenaIntegrityVerified=true` and `readyForNewLocalDraft=false`.
These checks verify internal consistency, **not** whether an external model
actually ran. Exit `2` means validation blocked; `0` means the inspected
snapshot passed these checks, **not** that any source is independently
authentic or that the deployed database contains the same records.

Before executing or persisting any model output, compare
`snapshotDerivedInputFingerprint` to the deployed
`GET /research-cycle/{cycle_hash}/athena-synthesis/input-contract`
fingerprint. A mismatch is a hard stop: the deployment or its dependencies
differ from the snapshot. An existing ATHENA artifact also blocks a new draft
(`readyForNewLocalDraft=false`) to avoid retrospective model shopping.
Never treat this read-only snapshot check as a substitute for deployed
authentication, external model execution evidence, or source corroboration.

## Canonical execution order (no fake evidence)

1. Obtain real instrument-specific PIT evidence with `availableAt` no later
   than the research `asOf`, independently verifiable HTTPS references,
   truthful source/provider identity, an immutable Journal revision and
   contradictory evidence. Do not reinterpret a current RSS retrieval as
   evidence that an article was available at an earlier historical `asOf`.
2. `POST /api/v1/recommendations/professional-research/research-cycle`
   validates and atomically persists Radar, Journal and Devil's Advocate.
   It **does not** persist News or ATHENA synthesis. Record its `cycleHash`.
3. For a cycle with `news` evidence, execute an **actual external model**
   against the canonical Radar evidence, retaining the model identity,
   assessment fingerprint, generation time and source references. Then POST
   `/research-cycle/{cycle_hash}/news-synthesis` with genuine
   `NewsAssessmentRequest` records. For `investors` evidence, the Investors
   synthesis must likewise exist; absence of a configured CIK is not evidence.
4. `GET /research-cycle/{cycle_hash}/athena-synthesis/input-contract` resolves
   the **current canonical** fingerprint after required category syntheses.
   An absent dependency fails closed; never synthesize a fingerprint by hand.
5. Execute a real identified model using that exact canonical input. POST
   `/research-cycle/{cycle_hash}/athena-synthesis` with truthful model
   provider/name/version, `inputFingerprint`, `generatedAt`, rationale,
   uncertainty and all required evidence IDs. The POST **validates an
   external output**, it does not itself execute the model.
6. Read both `/news-synthesis/latest` and `/athena-synthesis/latest` from
   the same deployed backend and confirm the canonical binding and provenance
   before accepting the Flutter presentation. Neither a successful POST nor
   a local fixture demonstrates production data coverage or predictive skill.

A `404` on `/latest` with "no synthesis persisted" means no stored artifact
in the database currently used by that process. Check the backend's
`ATHENA_DATABASE_PATH` and its authorized snapshot lineage **without
copying credentials into chat**. A `404` on `input-contract` may instead mean
that a required News or Investors category synthesis is absent. Retrying
`/latest` or inventing a JSON payload cannot resolve either dependency.

**Operational blockers still open:** verified model execution/corroboration,
real PIT evidence and source custody, deployed authenticated E2E, complete
365-day eligible-universe market history, longitudinal OOS outcomes, external
backup/restore and SMTP recovery acceptance. This runbook does not reduce
`MASTER_PROJECT.md` or `ROADMAP.md` scope or change completion percentages.

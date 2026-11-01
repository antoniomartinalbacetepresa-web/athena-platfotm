# Research synthesis: offline inventory and real-data activation

This runbook covers the observed local condition in which `GET .../athena-synthesis/latest`
returns `404: No existe ninguna ATHENA synthesis persistida` and
`GET .../news-synthesis/latest` returns `404: No existe ninguna síntesis News persistida`,
while `/api/v1/news/feed` responds `200`. A live RSS feed is **not** a persisted,
verified PIT synthesis; neither 404 proves the corresponding route is absent.


## Create a consistent offline snapshot from a local authorized SQLite database

When the operational database is accessible on the operator's machine, use
`create_consistent_research_snapshot.py` instead of copying its `.db` file
directly. SQLite's online backup API includes committed WAL transactions and
produces a separate checkpointed database without changing source rows or schema.
SQLite may still manage source WAL/shared-memory sidecars as part of normal
read access. The source is opened in read-only mode; the destination must not already
exist. This operation does **not** query market providers or execute Ollama.

From `backend` in PowerShell, with an existing access-restricted destination
directory and a **new** filename:

```powershell
.\.venv\Scripts\python.exe scripts\create_consistent_research_snapshot.py `
  --source "D:\secure-data\athena-operational.db" `
  --destination "D:\secure-snapshots\athena-consistent-20261101.db" `
  --acknowledge-sensitive-copy
```

The explicit acknowledgement is required because the copied database can
contain private account and portfolio information. Store the copy outside
web-served folders, cloud-synced public folders and the Git repository; restrict
filesystem ACLs (including Windows inherited permissions), encrypt and control
retention according to the operator's security policy. Do **not** upload the
snapshot or share its contents in chat. The command prints only the digest,
size and safety flags, not rows, paths or secrets. A successful
`sqliteIntegrityCheck=ok` confirms SQLite structural integrity of the
new copy; it does **not** prove source authenticity, operational market coverage,
external model execution, off-site backup success or production readiness.

Record `snapshotSha256` in a separately protected operator manifest. A hash
printed by the exporter and copied alongside the same database is **not**
independent chain-of-custody evidence. The existing canonical verifier accepts
that hash as `--expected-sha256` to detect later changes, but an independent
trusted manifest/backup procedure is still needed for operational attestation.
Never use a live database as `--snapshot`; only the new exported file is
eligible for immutable read-only verification. If the destination already
exists, the export fails without overwriting it.

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


## Read-only comparison with the actual deployed input contract

Once the checkpointed snapshot passes canonical verification, compare its
cycle/Radar/News/Investors hashes, exact PIT cutoff, evidence-set digest,
categories, canonical ATHENA input fingerprint and read-only authority
boundaries with the **actual backend**. This is a separate gate; a snapshot
alone cannot prove that the deployed backend uses the same database revision.

From `backend`, with an explicitly chosen **HTTPS origin** (no path, token,
credentials, or query string in the URL):

```powershell
.\.venv\Scripts\python.exe scripts\compare_deployed_research_input_contract.py `
  --snapshot "D:\secure-snapshots\athena-consistent.db" `
  --expected-sha256 "<SHA-256 FROM TRUSTED BACKUP MANIFEST>" `
  --cycle-hash "<EXISTING 64-CHAR CYCLE HASH>" `
  --backend-origin "https://YOUR-DEPLOYED-BACKEND"
```

For a backend running **on the same machine only**, use
`--backend-origin "http://127.0.0.1:8000" --allow-loopback-http`.
This development exception is never allowed for a non-loopback HTTP host.
The tool uses a bounded GET without redirects or ambient HTTP proxy settings,
does not transmit the snapshot contents, does not call Ollama, and does not
write to either database. It returns exit `0` only when the deployed contract
matches the trusted snapshot; exit `2` indicates a hard stop. A 404 indicates
that the backend has not persisted the cycle or required dependency syntheses
under the current deployment, **not** that the verifier should invent them.

The snapshot verifier also reports `newsProvenanceSha256` and
`investorsProvenanceSha256` (null when the corresponding category is absent).
These are canonical digests of the complete provenance bindings, not just the
artifact hashes. The deployed comparison must match the full News/Investors
provenance object against these digests, including assessment/source bindings
and presentation-only authority flags. This closes the previous gap where a
matching artifact hash plus a placeholder provenance object could pass.
The digests do not prove that external sources or model calls were authentic;
they only bind the two representations of the same persisted input.

The deployed gate now requires `requiredCoverage=all_cycle_radar_evidence` and
`canonicalCategorySynthesesRequired` to name exactly the required News/Investors
categories. Missing or weakened coverage declarations fail closed, even if
hashes match. Any advertised model execution, source authenticity or production
authority must not be interpreted as verified by this read-only gate.

**Important:** `snapshotReadyForNewLocalDraft` only describes the inspected
backup. The comparison deliberately reports `readyForNewLocalDraft=false`
and `deployedAthenaAbsenceVerified=false` even after a match: the input-contract
endpoint does not prove that a synthesis is absent from the live database, and
another process may have persisted one after the backup. Before any new draft
or persistence, an authorized operator must re-check current deployed state
and use server-side append-only/idempotency guards. Never promote the snapshot
readiness flag into authorization.

A successful comparison is a **point-in-time consistency check only**.
The deployed database may change after the GET, and the tool cannot attest
the external model, source authenticity, or production eligibility. It must
not be used to authorize automatic inference persistence, model promotion,
scoring, or trading. Do not pass a Gmail password, Ollama account credential,
broker token, or other secret to this CLI. If the endpoint requires an
authenticated operator, use an approved secure access method rather than
embedding a credential in the URL or chat.


## Optional deployed ATHENA readback against an already persisted snapshot artifact

When a **trusted checkpointed snapshot already contains a validated ATHENA synthesis**,
run the same comparator with `--verify-persisted-readback`. This makes an
additional read-only GET to the deployed cycle's
`/athena-synthesis` endpoint and requires the deployed response to contain
**exactly the same synthesis package hash** as the snapshot, with matching
input/output fingerprints, evidence set, provenance, PIT dates, append-only
metadata and no-advice/no-trading boundaries.

```powershell
.\.venv\Scripts\python.exe scripts\compare_deployed_research_input_contract.py `
  --snapshot "D:\secure-snapshots\athena-consistent.db" `
  --expected-sha256 "<SHA-256 FROM TRUSTED BACKUP MANIFEST>" `
  --cycle-hash "<EXISTING 64-CHAR CYCLE HASH>" `
  --backend-origin "https://YOUR-DEPLOYED-BACKEND" `
  --verify-persisted-readback
```

This mode **fails closed** if the snapshot contains no ATHENA artifact, the
deployed endpoint returns 404, or either response differs from the snapshot.
It does not infer that a 404 proves the live database is empty. A successful
`deployedPersistenceVerified=true` means the **GET returned an exact artifact
match at the time of the request**; it is not a durability test, a live backup
restore test, external model execution attestation, independent source
corroboration, authorization to generate a second draft, or permission to
trade. Never substitute synthetic fixtures for operational evidence.

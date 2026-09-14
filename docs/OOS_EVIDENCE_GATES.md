# Forecast-error OOS evidence gates

## Inference-derived prospective forecasts

The internal `generate_and_persist` workflow now calls the trusted executor's
`generate` operation. The unpersisted specification template fixes identity,
inputs, horizon and a forecast-availability deadline; its expected value is not
evidence and does not constrain the output. Observed finite `total_return` and
backend completion time determine the final expected value, availability and
specification hash. The original template is unchanged. Exact inputs are
revalidated, and the final specification and receipt-v2 are sealed atomically
using the existing tables. No caller can submit an execution observation here.

Generating against an existing identity/cycle-horizon is rejected before
inference. Retry the finalized specification with `execute_and_persist` instead.
Deployment still needs a real compatible runner, pinned model artifact and
prospectively selected cohorts. Cross-process first inference is not serialized;
write conflicts remain fail-closed. Synthetic runner regressions are software
evidence only, not productive forecasts, skill, approval or promotion authority.

Integrated workflow retries reload and validate an existing exact specification/
receipt-v2 pair before invoking the runner. They require the same model bytes and
deployment pin and preserve original execution identity and seal timestamps,
including after maturity. Missing/altered receipts or inputs fail closed rather
than triggering a new execution or retrospective repair. New executions retain
the existing temporal gates and atomic pair write. Concurrent first executions
are not serialized across inference; conflicting writes still cannot overwrite
existing evidence. These retry semantics do not establish longitudinal skill.

## Integrated observed forecast persistence

`RecommendationResearchExecutedForecastStoreService.execute_and_persist` is an
internal deployment workflow, not an HTTP receipt endpoint. It invokes the trusted
executor, validates the observed result, then persists the v3 specification and
receipt v2 in one SQLite transaction using the existing two tables. A receipt
write failure rolls back the specification insert; partial pairs cannot become
evaluation evidence. Clock/deadline checks occur under the write lock.

Receipt v2 binds the full execution observation and exact loaded JSON model bytes
(base64), while retaining disabled production/trading flags. Read validation
reconstructs original PIT payloads and checks observation/model/output bindings.
The public/declarative repository write path rejects v2; HTTP still only creates
v1 metadata, which cannot qualify for OOS. Model artifacts must contain only model
data, never credentials or secrets; deployment owns runner selection and pinning.

The atomic write uses an independently materialized, hash-checked payload snapshot
validated before acquiring the lock, avoiding legacy schema-initialization writes
from nested reads. Snapshot contents must still match each manifest content hash.
Read paths reload persistence rather than trusting that write-time snapshot.
This is not WORM storage or external timestamp attestation. It does not claim an
atomic cross-provider snapshot, predictive skill, sufficient longitudinal evidence
or human approval. A compatible real model, prospective cohort operations and
natural horizon maturity remain operational gates; synthetic E2E tests demonstrate
the software flow only. Duplicate executions cannot replace existing receipts.

Execution observations now have a reusable `validate_observation` read/persistence
boundary. It verifies the observation hash, disabled authority flags and exact
specification, reconstructed manifest/payloads, model-byte identity, output and
temporal bindings. Rehashing altered metadata cannot bypass these semantic
checks. Execution uses this validator before returning, and validated records
are detached copies. This is integrity verification for trusted storage, not
proof of observation origin: the integrated receipt-v2 writer remains required
and OOS eligibility is unchanged.

The executor freezes an independent copy of the entire prospective specification
before inference and rejects changes to the original contract during the runner
call. Output binding cannot be switched by editing the expected value, input
manifest or availability timestamp through a retained reference. Oversized integer
outputs are rejected as nonfinite numeric outputs rather than leaking overflow
exceptions. These checks do not open the v2 persistence or OOS gates.

## Internal trusted-runner execution adapter

`RecommendationResearchModelExecutorService` checks a deployment-pinned SHA-256
against the exact model bytes passed to a deployment-selected runner. Its JSON
data envelope must identify model name/version, `total_return` and the exact
horizon. Executable deserialization/imports are not supported; duplicate JSON
keys, nonfinite data and prohibited model identities are rejected. This adapter
does not train a new model or reinterpret an excess-return model as total return.

It materializes the existing v3 manifest, invokes the runner with those detached
payloads and bytes, and reads start/completion times from the backend clock. All
inputs must be available by start, completion cannot precede start or exceed
forecast availability, and the runner cannot mutate the supplied snapshot.
The observed finite total-return output must match the prospective specification.
Its observation binds exact byte hash, input manifest/snapshot hashes, output
hash, specification hash and a server-generated execution identity.

The runner implementation and artifact pin remain a trusted deployment boundary,
not HTTP request fields or independently attested facts. This component has no
public endpoint, new database, specification writes or receipt-v2 minting. It is
not sufficient to qualify OOS: model availability/precommitment and the integrated
execution → specification persistence → receipt-v2 path remain open. The existing
fail-closed gate is unchanged. Synthetic runner tests establish software behavior,
not availability of a trained production model, predictive skill or longitudinal
evidence. All production-learning/promotion/trading flags remain false.

## Materialized execution inputs

`PersistedForecastInputManifestService.materialize_specification` validates v3,
resolves only the supported macro/market namespaces, and returns a detached
snapshot with `specificationHash`, `inputManifestHash` and exact input content.
Macro content is the validated observation artifact plus normalized persistence
timestamp; market content is the exact persisted row. These are the same objects
used to calculate each evidence `contentHash`, loaded once per selection rather
than verified and then independently reread. Mixed families retain canonical
`sourceRef` ordering and the 200-input bound.

The reconstructed evidence must exactly match the supplied manifest. Missing,
changed, late or unsupported inputs fail closed; caller modifications to the
returned snapshot do not modify persistence or the original manifest. Family
`resolve` methods retain their existing evidence-only contracts and reuse these
materializers, avoiding a parallel data path or database.

This is an internal payload adapter for a future trusted executor, not a public
endpoint, new predictive model, model run or production forecast. It does not
establish source quality, atomic cross-repository snapshots, external timestamp
attestation or predictive skill. Model execution/artifact availability and
prospective longitudinal evidence remain separate open gates.

## Receipt seal chain and retry semantics

Receipt validation independently requires a timezone-aware physical specification
seal with `forecast.availableAt <= specification.created_at <= periodStart`.
Receipt storage/read validation additionally requires
`specification.created_at <= receipt.created_at <= periodStart`, alongside the
existing execution/input ordering. A valid hash alone cannot substitute for
these physical metadata checks.

Identical receipt retries reuse the original validated record and timestamp,
including after maturity; different receipts cannot replace it. New receipts
remain blocked after `periodStart`. Identity lookup and insert are serialized
with a SQLite write transaction; the clock is sampled after acquiring the lock
and only for new records, so lock waits cannot backdate a new seal.

The current receipt still binds **declared** model identity, artifact hash,
execution timestamp and output copied from the specification. It does not run
the model, resolve executable artifact bytes or independently observe its output.
Consequently it must not be counted as proof of actual model execution or
longitudinal production evidence. The integrated trusted executor/input-payload
adapter and compatible total-return model remain open gates; no production
promotion or trading authority is granted by a receipt.

## Persisted summary reads replay their evidence

GET `forecast-error-oos-summary/{summary_hash}` reloads the summary's exact
`errorHashes`, their specifications and any resolvable persisted macro/market
inputs. It rebuilds the descriptive summary at its original `asOf` and compares
the entire artifact, not only its hash or metrics. Missing or altered sources,
late specification seals, and errors unavailable at that original cutoff fail
closed. Storage failures do not fall back to an unverified cached snapshot.
Revalidation never rewrites the append-only summary or extends its PIT cutoff.

This closes an API read-path integrity gap; it does not certify actual model
execution, verify the entire outcome lineage, or create longitudinal evidence.
The existing shadow ridge candidate predicts benchmark-relative **excess**
returns, whereas evaluation specifications target **total** returns. Connecting
that candidate requires an explicit compatible economic contract; relabeling
its output as total return is not an acceptable execution receipt. Model artifact
availability, exact executable input lineage and execution/output binding remain
open engineering gates, with production promotion and trading still disabled.

## Persisted macro inputs bridge

The separate POST route
`/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/persisted-macro-evaluation-specification`
accepts forecast fields and `macroObservationKeys` instead of trusting a supplied
input manifest. It reuses `RecommendationMacroPitObservationRepository` and the
existing v3 specification store. No new forecast or macro database is introduced.

Each selected record is hash-validated by the macro repository. Both publication
availability and physical persistence must precede or equal the frozen cycle
cutoff, which in turn must precede or equal forecast availability. The manifest
uses `urn:athena:macro-pit:{observationKey}` references and a SHA-256 over the exact
artifact plus its normalized persistence timestamp; effective input availability
is the later of publication and persistence. Selection is bounded at 200 unique
keys and ordered canonically. Historical data ingested later cannot retroactively
qualify for an earlier cycle merely because its publication date is older.

The API reverifies these resolvable references before specification persistence,
on specification reads, before forecast-error calculation, and before summary
construction. Missing records, changed payloads, changed persistence metadata,
or a manifest differing from reconstructed content fail closed. A manifest using
this namespace must consist entirely of supported macro references; mixed or
unresolvable namespaces do not gain partial verification.

Other v3 manifests remain declared research inputs, not automatically certified
persisted data. This bridge only covers the existing supported macro providers;
market, filings, news, model-input lineage, prospective cohort preselection,
actual model execution, longitudinal evidence, and governed promotion remain
separate work. It does not claim external timestamp attestation, source quality,
predictive skill, or production eligibility.

These checks extend the existing descriptive OOS pipeline. They do not approve
models, select thresholds, establish predictive skill, or enable trading.

## Temporal eligibility

`RecommendationResearchForecastErrorOosService` requires every cohort row,
including rows without measured forecast errors, to have timezone-aware start
and end timestamps, a positive exact elapsed horizon, and an end no later than
the cohort's own PIT cutoff. A later diagnostic cutoff cannot retrospectively
make an immature cohort row eligible.

Each supplied forecast error must independently have a matching exact elapsed
horizon, be mature at the diagnostic cutoff, and have been persisted no earlier
than its period end and no later than that cutoff. Comparisons use instants,
not timestamp text, and preserve microseconds and timezone offsets.

## Evidence sufficiency

`LongitudinalOosSufficiencyPolicyService` continues to require an exact policy
fingerprint, human approval, temporal precommitment, evaluation span, distinct
periods, eligible outcomes, issuer diversity, and required horizons.

The existing minimum-outcome threshold must now also be met by actually
measured forecast errors. Each required horizon must contain at least one
measured forecast error; merely appearing in cohort metadata is insufficient.
No threshold values are selected or lowered by these checks. This stricter
validation may invalidate a previously passing diagnostic with missing errors.

## Physical precommitment boundary

New evaluation specifications must be sealed no later than `periodStart`, not
merely before `periodEnd`. Read validation also rejects legacy rows sealed after
the start; changing declared `forecastEvidence.availableAt` does not rescue
them. Repeating an identical, already valid append after maturity returns its
original immutable record rather than creating a new seal.

The summary builder independently checks specification sealing timestamps and
error maturity, and binds instrument, symbol, metric, horizon, and expected
value to the exact specification. A self-consistent error hash alone cannot
justify attaching a different instrument or target to that specification.

Version 1 fixes `periodStart` at the frozen cycle cutoff. Consequently, attaching
a forecast to an already past cycle is intentionally blocked. Operational
forecast generation must precommit prospectively; a future contract that uses
a later start must explicitly version that period definition and align outcome
attribution, rather than silently backdating a timestamp or changing v1.

## Explicit prospective contract v2

The separate POST route
`/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/prospective-evaluation-specification`
accepts the existing forecast fields plus a required timezone-aware
`periodStart`. It produces `research-evaluation-specification-v2`, with
`periodStart > cycleAsOf` and `periodEnd = periodStart + horizonSeconds`.
The original endpoint and v1 period definition are unchanged.

The cycle cutoff is retained, not moved forward to the forecast-generation
time. The output forecast may become available after that cutoff, but must
already be available at the repository-controlled sealing time, which must be
no later than the selected period start. New writes and read validation enforce
this availability boundary; summaries check it independently. The POST response
includes the original `persistence.sealedAt` on idempotent retries.

The existing unique `(cycle_hash, horizon_seconds)` target remains in force:
v2 does not allow replacing a sealed forecast by moving its start or changing
its method, expected return, or version. Both contracts share the same storage
and verification path; no parallel forecast database was introduced.

Existing outcome attribution already allows periods after the cycle cutoff.
Forecast errors and summaries still require the exact specification period.
The summary builder rejects pooling v1 and v2 even for the same method and
horizon. The new lifecycle regression uses the existing attribution, outcome,
specification, and error repositories with deterministic test evidence only.

This is a prospective submission contract, not a new automatic forecasting
model or a production scheduler. It does not prove that an external method's
inputs were PIT-safe just because its output was sealed on time. Model-input
provenance, cohort preselection, and longitudinal production evidence remain
separate gates.

## PIT-bound prospective contract v3

The route
`/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/pit-safe-prospective-evaluation-specification`
extends the v2 prospective request with a non-empty `inputEvidence` manifest.
Each entry binds `source`, `sourceRef`, a timezone-aware `availableAt`, and a
SHA-256 `contentHash` into the immutable specification hash.

V3 requires every input to have been available no later than the declared
forecast output. The existing repository boundary independently requires the
forecast output to have been available by the repository-controlled seal, and
the seal to occur no later than `periodStart`. Together the accepted temporal
chain is therefore `input.availableAt <= forecast.availableAt <= sealedAt <=
periodStart`. Naive timestamps, duplicate content hashes, forbidden FMP sources,
and post-hoc manifest changes fail closed.

V3 uses the existing append-only specification repository and the same outcome,
forecast-error and OOS verification path. It does not introduce a second
forecast store, alter v1/v2 semantics, lower any OOS threshold, or authorize
automatic promotion, model mutation, weighting, or trading.

A content hash proves identity of the declared input bytes, not their quality,
correctness, independence, completeness, or economic relevance. Accordingly,
`inputQualityClaim` remains explicitly `forbidden`, and fixtures only validate
software behavior. Real longitudinal production evidence and source-quality
acceptance remain separate gates.

## Remaining boundaries

The OOS service consumes records verified by the existing repository and
summary-integrity layers; temporal validation is not a replacement for hash
verification or proof of source quality. Maturity alone also does not prove
that a forecast was physically sealed ex ante: specification persistence and
cohort selection must retain their separate precommitment checks.

These timestamps are repository-controlled, but they are not externally
anchored WORM or signed timestamp evidence. Privileged database modification
and historical summaries without retained sealing metadata remain separate
hardening/provenance concerns; these checks do not claim to close them.

Real longitudinal evidence, an approved sufficiency policy, dependency-aware
stability assessment, and separately governed promotion remain necessary.
`productionLearningEligible` and `productionSufficiencyClaimed` remain false.
Synthetic regression cases exercise software behavior only, not operational
readiness or predictive performance.

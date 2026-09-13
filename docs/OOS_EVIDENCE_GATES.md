# Forecast-error OOS evidence gates

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

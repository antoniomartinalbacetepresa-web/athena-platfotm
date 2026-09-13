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

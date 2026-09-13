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

## Remaining boundaries

The OOS service consumes records verified by the existing repository and
summary-integrity layers; temporal validation is not a replacement for hash
verification or proof of source quality. Maturity alone also does not prove
that a forecast was physically sealed ex ante: specification persistence and
cohort selection must retain their separate precommitment checks.

Real longitudinal evidence, an approved sufficiency policy, dependency-aware
stability assessment, and separately governed promotion remain necessary.
`productionLearningEligible` and `productionSufficiencyClaimed` remain false.
Synthetic regression cases exercise software behavior only, not operational
readiness or predictive performance.

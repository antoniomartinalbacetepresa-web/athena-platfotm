# Longitudinal OOS: measured diversity evidence boundary

The human-approved longitudinal sufficiency policy must not be marked
`acceptanceEvidenceVerified=true` using only aggregate counts. A positive
result now requires **both** measured distributions:

- `issuerErrorCounts`, with `resolvedIssuerErrorCount` and
  `maximumErrorsPerResolvedIssuer`, reconciled against each horizon's issuer
  distribution and measured error count.
- `periodEndErrorCounts`, reconciled against each horizon's exact period-end
  distribution, distinct period count, first/last period end and measured span.

Omitting either distribution makes the policy **not satisfied** even when
scalar totals, approved thresholds, and prospective timing look plausible.
Malformed or contradictory supplied maps remain fail-closed. This is a
deliberate change from older test-only scalar examples, not a change to the
human-selected thresholds. Existing tests with a satisfied synthetic policy
now provide internally consistent *both* maps.

The result remains descriptive: `productionSufficiencyClaimed=false`,
`automaticApproval=false` and `automaticProductionPromotion=false`.
A policy match does not prove genuine operational observations, independent
market outcomes, predictive skill, signed timestamps, or deployment approval.
Those require a real precommitted cohort, physically persisted horizon-matured
outcomes, externally authorized provenance, and independent operational review.
Do not use fixtures as evidence of production readiness or authorize learning,
weighting, advice, or trading through this policy.

## OOS diagnostic input reconciliation (2026-11-01)

The research forecast-error OOS diagnostic now rejects inconsistent stored
error arithmetic (signed, absolute and squared errors must match the persisted
expected and realized values). It also reconciles the cohort-wide eligible
outcome count and every exact-horizon count and duration against actual cohort
rows **before** computing measurement coverage, including when no forecast
errors have matured. A forged denominator cannot inflate or dilute apparent
longitudinal coverage.

These are structural checks, not independent proof of a persisted hash,
source capture time, corporate-action provenance, or predictive skill. The
underlying persistence layer must continue to verify canonical artifact hashes
and PIT records; no operational OOS cohort is claimed by these regressions.

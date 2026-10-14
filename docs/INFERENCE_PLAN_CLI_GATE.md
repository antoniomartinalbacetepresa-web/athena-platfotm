# Manual generation selection gate

New CLI generation requires --plan-id for an existing ResearchInferenceSelectionPlanService plan. The exact template must be selected, the reviewed model hash must match and the physical seal must be available before generation. Failure never falls back to inference. Recovery remains read-only and needs no fabricated historical plan.

The immutable plan retains every selected template even when generation fails or never runs. This CLI gate does not yet bind finalized forecasts/attempts into governed OOS or prevent direct internal store calls. Do not claim selection-bias closure, model skill, production eligibility or sufficient empirical evidence. Next: bind observations and missing/failed attempts to this denominator in governed OOS. No automatic promotion or trading.

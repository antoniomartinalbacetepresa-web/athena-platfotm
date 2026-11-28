# Operational legacy recommendation-outcome evaluation — write cutoff

The manual `backend/scripts/evaluate_due_recommendations.py` CLI **writes**
legacy recommendation outcome rows. Its `evaluated_at` is an evidence timestamp,
not an arbitrary historical backtest date. Before opening the database, the CLI
now rejects a future `--as-of` or one older than five minutes relative to the
UTC wall clock. A missing `--as-of` uses the current UTC instant. A rejected
cutoff exits with code 2 **without invoking the evaluator**. This prevents
operators from creating newly persisted outcomes falsely dated months earlier
through the CLI. It does not prove independent time attestation, and the
underlying Python service/repository remain callable by trusted internal code.

Use `--require-complete` when an operator needs a fail-closed batch gate:
exit 3 if any due row is skipped or if the due/evaluated counts differ. Zero due
rows can legitimately return 0; that is **not** a successful longitudinal
cohort or predictive-skill claim. Without the flag, the existing interactive
exit-code behavior is preserved, and the JSON report still lists all skips.

Historical PIT research must be performed through read-only diagnostics or
prospectively persisted evidence, **not** by retroactively minting outcome rows.
This CLI does not establish OOS precommitment, independent market-data origin,
corporate-action adjustment quality, real 365-day eligible-universe coverage,
human model approval or production learning eligibility. It never authorizes
automatic weighting, investment orders or trading. The separate prospective
research cohort remains governed by its own sealed specifications, actual
persisted outcomes and maturity checks.

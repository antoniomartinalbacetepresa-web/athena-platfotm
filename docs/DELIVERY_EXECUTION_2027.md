# ATHENA TYCHE — execution and recovery contract (2026-11-22)

Target: full approved scope by **2027-03-17**. This is a target, not a forecast or proof of completion. Do not change `main`; all implementation work stays on `dev/real-market-backend`.

## Sources of truth
Read `docs/MASTER_PROJECT.md`, `docs/ROADMAP.md`, `docs/ACCEPTANCE_INVENTORY.md` and any relevant module contracts. Never reduce the approved scope or claim old percentages as certified. The acceptance inventory is partial; current completion percentage is **not certifiable**.

## Execution sequence for every hourly run
1. Verify exact branch HEAD SHA, available push CI and PR CI for that SHA, previous checkpoint, critical regressions and outstanding blockers. Missing CI evidence is **unknown**, not green.
2. Pick one observable vertical capability; normally perform 2–3 connected changes (up to 4–6 only when independently testable). Keep no more than four logical blocks A=Market/data, B=News/Investors/ATHENA, C=Flutter/Portfolio/Radar, D=CI/security/acceptance. Prioritize red critical CI before feature expansion.
3. Implement on the allowed branch, validate focused tests and integration, commit with evidence. Do not confuse a successful commit with a tested release. Do not invent test runs, provider licenses or deployed access.
4. Record a concise checkpoint: exact starting/ending SHA, changes, tests executed/not executed, push/PR CI URLs and event, acceptance IDs affected, actual user-visible result, blockers and the next smallest verifiable step.
5. If there is no real development environment or no permissions to run tests, disclose the precise limitation; do not generate fictitious progress. Do not ask for secrets in chat.

## First vertical dependency chain
Licensed real Market history (>=365 days for eligible pilot), price/volume, source rights, timestamp/PIT, splits/dividends, FX, gaps and freshness -> real news evidence -> idempotent persisted canonical research cycle -> risk/valuation and contradictory evidence -> Flutter selected-instrument experience with honest loading/empty/stale/error states. Ollama qwen3:1.7b is optional and explanatory only; its failure cannot block core research. Research-only; no live broker orders or automatic trading.

## Time management
- **Every hour:** execute and report evidence, not just a status narrative.
- **Every 6 hours:** inspect the critical path, repeat blockers and remaining capacity.
- **Every 24 hours:** require at least one genuinely observable advance or explain why not; if none, change the approach, not merely the wording.
- **After 2 blocked cycles:** escalate the same blocker rather than retrying unchanged.
- **After 72 hours without progress:** reassess the execution environment, authorized tools, provider access and staffing.
- **Weekly:** close acceptance-backed vertical capabilities, not arbitrary commit quotas.
- **Every 15 days:** reconcile the complete scope, release gates and an evidence-backed schedule forecast. Do not infer velocity from task counts.

## Release gates
All approved scope represented in the acceptance inventory; licensing/coverage and PIT verified in an authorized environment; backend + Flutter integration/E2E; authentication/owner isolation, backup/restore, secrets and incident response; exact-SHA CI; Windows operation; performance, accessibility and no-order boundaries. No production-ready or 100% claim without all mandatory evidence.

## Current blocking questions (not yet verified)
- Is an executable persistent development/test environment connected to the hourly automation?
- Can that environment run backend pytest, Flutter analyze/test/build, and E2E on the correct branch?
- Are provider licensing and actual 365-day coverage proven?
- Are push and PR CI checks visible for the exact branch HEAD?
- Does the inventory fully cover all approved future modules and enhancements?

Never overwrite this checkpoint with fabricated status. Keep concrete execution records in versioned changes or the automation run report.

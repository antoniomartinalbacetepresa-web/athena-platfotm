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

## Mandatory technical unblockers — execution order (2026-11-22)

### Gate E: executable development environment (critical)
Before claiming accelerated delivery, identify the **actual** execution host for the hourly automation, its persistent checkout/worktree, branch, runtime versions and writable scope. Demonstrate, with logs, a non-destructive checkout of `dev/real-market-backend`, backend dependency installation and focused pytest, Flutter analyze/test/build if Flutter is installed, and a repeatable restart of the same checkpoint. GitHub API file-write permission is **not** proof of a shell, a persistent computer, Python/Flutter runtimes or test execution. If absent, report `BLOCKED_ENVIRONMENT` and request authorization to connect a supported persistent execution environment; never pretend it exists or install on the user's Windows machine remotely.

### Gate CI: actual GitHub Actions evidence (critical)
Discover the **real workflow paths** in the repository before editing any YAML; do not guess a workflow filename or create a duplicate. Confirm that existing workflows trigger on push to `dev/real-market-backend` and PRs **targeting that branch**, run backend pytest and Flutter analyze/test/build where appropriate, and expose the mandatory release gate. Verify the exact commit SHA, trigger event, run URL, conclusion and whether the run belongs to push or PR; an empty status list or no PR run is `UNKNOWN`, not a pass or a failure. Change existing CI only after inspecting it and its repository conventions. Never change branch protections or secrets without authorization.

### Gate DATA: legally usable real market inputs (critical)
Select a liquid pilot instrument and document candidate primary and independent secondary data providers, free/paid tier, rights to storage/redistribution, adjustments, API limits, historical depth, intraday availability and cost. Verify source agreement and actual >=365-day OHLCV coverage with timestamps, volume, splits/dividends, currency/FX, gaps and PIT in an authorized running environment. If provider rights or credentials are absent, mark `BLOCKED_DATA_LICENSE`; implement honest fail-closed UI/API states and provider contracts without fabricating live coverage. Do not purchase plans or request secrets in chat.

### 48-hour evidence-based trial
At the next two-day checkpoint, record: (a) execution environment available yes/no and its test log, (b) exact-SHA push/PR CI status, (c) pilot data provider rights and measured coverage, (d) at least one demonstrable code-integrated vertical advance or its precise blocker. If no advance, recommend changing the execution environment, staffing or provider strategy. Never declare this trial passed because a document or prompt changed.

### Reporting
Separate VERIFIED, BLOCKED, UNKNOWN and NOT RUN. Preserve all previously approved modules and safety boundaries. Keep scope complete; sequence work according to critical path. These gates supersede narrative progress claims but do not authorize live trading.

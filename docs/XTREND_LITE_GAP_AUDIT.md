# XTrend Lite comparison — evidence-led gap register (2026-11-09)

This is a **provisional gap register**, not a verified feature audit of XTrend Lite and not an operational acceptance claim. Advertising does not prove reliability or investment outcomes. Source-of-truth for ATHENA scope remains `docs/MASTER_PROJECT.md`, `docs/ROADMAP.md` and `docs/ACCEPTANCE_INVENTORY.md`. No trading orders, copy trading or promotional bonuses are in scope for the current read-only/paper release.

## Classification rules

- **Verified implemented:** cite exact source path, focused test and passing CI at the exact commit SHA.
- **Partial / not integrated:** existing component is documented but the user-visible end-to-end acceptance is not evidenced.
- **Absent:** only after a repository-wide code/API/UI/test inspection demonstrates absence.
- **Blocked:** an external license, deployment or real-clock operational proof is indispensable.
- **Unverified:** evidence has not been inspected; do **not** infer absence.

| Capability | Current evidence in project documents | Classification | Next observable acceptance |
| --- | --- | --- | --- |
| 1. Single instrument dossier | ROADMAP describes Market universe/history, News feed/synthesis, risk and ATHENA synthesis separately; acceptance inventory CORE-001–003 / PRODUCT-001 is not certified. | Partial / not integrated; licensed live operation blocked | Selecting a liquid ticker opens price, adjusted volume, fundamentals, news and canonical risk/valuation research in one Flutter journey, with instrument identity, license, observationAt, availableAt, retrievedAt, coverage gaps, FX, staleness and explicit failure states. |
| 2. Explainable alerts | MASTER_PROJECT v2 includes intelligent alerts; PRODUCT-008 remains pending. Existing alert code has **not** been audited. | Unverified | Configurable opt-in price/RVOL/breakout/prior-25-session-low/earnings/thesis alerts, PIT provenance, deduplication, expiry and no-order disclaimer; tests for late/out-of-order data and false triggers. |
| 3. Economic/corporate calendar | MASTER_PROJECT includes macro and corporate earnings; dedicated calendar implementation has **not** been audited. | Unverified | Source-attributed corporate/macro events, event timezone and published/available-at times, revision history, deduplication, and explicit unknown-date state; no invented event dates. |
| 4. Hypothesis paper simulator | ROADMAP documents shadow/OOS infrastructure and Portfolio accounting; integrated user-facing simulator is not established. | Partial / not integrated | Versioned precommitted entry/exit rules, benchmark, splits/dividends, spread, fees, slippage, liquidity, drawdown, walk-forward and survivorship checks; never send broker orders. |
| 5. ATHENA AI explanation | ROADMAP describes canonical News/ATHENA synthesis and fail-closed provenance; local Ollama qwen3:1.7b remains opt-in and not verified on user hardware. | Partial / not integrated | Evidence-bound JSON explanation with contradiction citations, uncertainty, clear unavailable-model state, and unchanged deterministic research output when Ollama is off. |

## Prioritized delivery slices

1. **A + D: Pilot dossier contract.** Inspect actual Market/News/ATHENA endpoints and Flutter clients; reuse existing models. Introduce shared fail-closed provenance and freshness fields only where genuinely missing, with backend/Flutter contract tests. Before accepting live data, independently establish provider license/redistribution rights, 365-day coverage, corporate-action adjustments and real-clock timestamps. Never equate Yahoo or RSS accessibility with a license.
2. **A + C: Single-screen journey.** Connect selected instrument to canonical persisted research and existing News presentation; show loading, unavailable, expired, conflicting and insufficient-history states. Validate an authenticated/guest-appropriate Flutter E2E with a real permitted pilot provider; synthetic fixtures count only as regression coverage.
3. **B + C: Alerts, calendar and paper simulation.** Audit existing services before implementing missing parts. Reuse Opportunity & Exit Radar and precommitted OOS infrastructure, keeping notification permissions opt-in and all decisions human-controlled.

## Acceptance and accounting

Map dossier to CORE-001/002/003 and PRODUCT-001; alert/calendar to PRODUCT-008 and CORE-008/014 where relevant; simulator to CORE-004/005/012 and PRODUCT-012; AI to CORE-009/014 and PRODUCT-011. These are **cross-references**, not additional weighted completion credit. Do not mark any criterion complete from this document. The acceptance inventory remains incomplete, so both core and product **percentage current not certifiable**.

## Next repository inspection checklist

Inspect exact branch HEAD, push-triggered workflow runs for that SHA, PR checks targeting `dev/real-market-backend`, AGENTS instructions if present, and actual API/Flutter/test paths. Prioritize a red critical gate before coding. Verify `--real-clock` and CI `py_compile` behavior rather than assuming. If unavailable, record the missing evidence and implement only a narrowly scoped independent change with tests. No access to the user's local Ollama or licensed vendor account is implied.

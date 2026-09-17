# ATHENA TYCHE — Engineering Completion Roadmap

Updated: 2026-09-17

This roadmap measures software completion against `docs/MASTER_PROJECT.md`. It does not measure investment performance, predictive skill, profitability, or production authorization.

## Scoring rubric

- **0%**: absent.
- **25%**: scaffold/data model exists.
- **50%**: functional UI or service exists.
- **75%**: integrated with real data and covered by meaningful tests.
- **100%**: acceptance criteria complete, production-safe for its intended scope, and CI green.

Percentages are conservative engineering estimates. They may move down if an audit discovers missing acceptance criteria or unsafe assumptions.

## Analytical core status

| Area | Progress |
| --- | ---: |
| Backend / arquitectura | 94% |
| Datos / PIT / provenance / identity / FX | 98% |
| Analysis engines | 95% |
| Recommendation | 92% |
| Learning / validation | 88% |
| Portfolio / diversification | 95% |
| Investors / News | 84% |
| Flutter / UI | 91% |
| Expectations Gap | 88% |
| Reverse Valuation | 90% |
| Scenario Asymmetry | 88% |
| Catalysts | 90% |
| Thesis Invalidation | 91% |
| Factor Risk | 97% |
| Performance Attribution | 97% |
| Investment Journal | 90% |
| Devil’s Advocate | 90% |
| ATHENA Radar | 90% |

**Conservative analytical-core completion: approximately 91%.**

This number measures the analytical and investment-research core only. It must not be reported as total product completion.

## Whole-product status

| Area | Progress | Current evidence / remaining work |
| --- | ---: | --- |
| Core architecture & backend | 94% | FastAPI, repositories/services, database migrations, readiness diagnostics, authentication, encrypted owner-scoped profile persistence and verified SQLite backup/recovery services exist. Remaining: production hardening, protected merge gates and final cross-module acceptance. |
| Welcome & navigation | 90% | Welcome, account login/registration/recovery, guest mode, Dashboard, Market, News, Portfolio and Profile routes exist. Remaining: final end-to-end navigation/accessibility acceptance. |
| Dashboard | 85% | Responsive dashboard, live panels and operational readiness surface exist. Remaining: end-to-end states and final UX acceptance. |
| Market | 80% | Real persisted universe, regional ingestion, market-cap/canonical identity logic and standalone UI exist. Remaining: canonical weighting evidence, production coverage and deeper historical acceptance. |
| News | 75% | Verified backend feed remains separate from the canonical latest News synthesis. Flutter now consumes the canonical synthesis fail-closed and presents model summary, importance, estimated impact magnitude/direction, confidence, publisher/model identity and HTTPS provenance. Acceptance coverage verifies the canonical endpoint, rejects FMP and authority escalation, and proves 404/503/retry cannot fabricate or retain stale synthesis. Exact-SHA CI `40b48461151bb9905f3a3c8fa9b298d5efdde23d` passed. Remaining: broader navigation/accessibility/E2E acceptance and production evidence for the external synthesis execution/corroboration; model output remains presentation-only and cannot influence recommendations, scoring or trading. |
| Portfolio | 88% | Portfolio UI plus valuation, concentration, correlations, attribution/reconciliation and accounting infrastructure exist. Authenticated personal positions are isolated server-side by JWT-derived ownership. Declared average purchase price is persisted with AES-256-GCM and synchronized only through authenticated transport. The owner-scoped append-only Event Ledger is exposed through an authenticated read-only history API with PIT `asOf` filtering; A/B regression proves that equal logical `portfolioId` values do not cross account boundaries. Flutter consumes that same ledger through a typed fail-closed model and exposes loading, empty, error/retry and event-list states from the authenticated Portfolio entry point without creating a second history store. Remaining: broader Portfolio E2E/UX acceptance and production key-management evidence. |
| Profile & authentication | 91% | Argon2 hashing, signed expiring JWT with unique jti/session version, register/token/me/logout/logout-all/change-password APIs, persistent token revocation, persistent login throttling, Flutter auth client support, guest mode and durable token persistence in platform secure storage exist. Bearer-token payloads minimize identity PII while `/auth/me` resolves legitimate identity data server-side. Account closure purges owner-scoped Profile/Portfolio state and anonymizes direct identity atomically. Account recovery has one-time cryptographic tokens stored only as SHA-256 digests, 30-minute expiry, persistent request throttling, configurable SMTP delivery requiring an HTTPS public recovery URL, password reset, token replay rejection and all-session invalidation after reset. Flutter exposes a tested recovery flow and validates restored tokens against `/auth/me`. Profile preferences use authenticated encrypted persistence with no insecure local fallback. Remaining: verify SMTP delivery in the real deployment and complete broader account-lifecycle/E2E acceptance. |
| ATHENA AI & recommendations | 78% | Research, catalysts, invalidation, factor risk, attribution, journal, devil's advocate, radar, shadow/OOS and diagnostics exist. Canonical ATHENA synthesis and user-facing Dashboard presentation are provenance-bound and fail closed. Remaining: broader final synthesis UX acceptance and longitudinal evidence thresholds. |
| Market history | 79% | One-year Yahoo history requests, immutable PIT observations, source-continuity depth diagnostics, corporate-action extraction/ingestion, schema migration and cross-provider reconciliation diagnostics exist. Diagnostics and final acceptance require >=365-day current depth for 100% of the eligible universe. Secondary backfill enforces its expected provider family and reconciliation never auto-selects a provider on conflict or absence. `productionCoverageClaimed=false` remains explicit. Remaining: measured real >=365-day current eligible-universe coverage, operational verification of an independent secondary corporate-action feed with measured agreement, and final adjustment-quality evidence. |
| Continuous learning | 70% | Calibration/drift/evaluation/shadow/OOS infrastructure exists. Remaining: sufficient real longitudinal OOS evidence and controlled promotion policy. |
| Personalization | 75% | Owner-scoped risk tolerance, investment horizon, base currency, objective, experience level, liquidity need, maximum drawdown tolerance and available capital have validated AES-256-GCM persistence, authenticated Flutter transport and Profile UI load/save/reload/delete. Presentation-only personalization cannot influence recommendation scoring, canonical weighting, automatic learning promotion or trading. Versioned key rotation/migration is transactional and fail-closed. Remaining: deployment key-management procedure, broader cross-surface E2E/UX acceptance and production operational evidence. |
| Security & production hardening | 93% | Fail-closed auth secret, Argon2, JWT revocation/session rotation, authenticated password rotation, portfolio authorization, throttling, secure token storage, AES-256-GCM profile encryption, atomic account closure, one-use recovery tokens, transactional key rotation and verified SQLite backup/recovery drills are covered. `/api/v1/readiness/security` checks deployment configuration without returning secrets or claiming production verification. Remaining: real recovery delivery, secret-manager custody/rotation evidence, scheduled/off-site backup operation, operational incident-response acceptance and required branch checks. |
| Testing & CI | 97% | Backend pytest plus Flutter analyze/test validate pushed changes. Security, auth, Profile, Portfolio, market-history, corporate-action, recovery, provenance and News synthesis acceptance have dedicated regression coverage. Remaining: mandatory protected-branch checks, broader cross-surface E2E/security/recovery-delivery and release gates. |

**Overall whole-product engineering completion: approximately 84%.**

## Definition of 100%

ATHENA reaches 100% engineering completion only when every whole-product area above is at 100%, all mandatory CI/release gates pass, no critical blocker remains open, and documentation matches implemented behavior. A readiness diagnostic or analytical-core score reaching 100% does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish the authentication lifecycle: verify the configured recovery-delivery channel in the real deployment and complete remaining account-lifecycle/E2E controls.
2. Finish authenticated Portfolio acceptance and encrypted Profile personalization with broader cross-surface E2E/UX acceptance while preserving privacy/no-authority contracts and avoiding insecure local persistence.
3. Complete production recovery operations: real scheduled/off-site backups, deployment secret-manager custody/rotation and operational incident-response acceptance.
4. Reach real historical depth/coverage, operationally verify the independent secondary corporate-action source and require measured reconciliation/adjustment quality gates before treating history as production-ready.
5. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
6. Close longitudinal OOS and forecast-error evidence gates without fabricated/synthetic production evidence.
7. Complete broader final News/Investors/ATHENA cross-surface UX/E2E acceptance while preserving provenance and no-authority boundaries.
8. Make CI checks mandatory on protected branches and add E2E/security/release gates.
9. Re-audit every area against `MASTER_PROJECT.md`; only then mark 100%.

## Latest validated increment

- Exact-SHA CI for `40b48461151bb9905f3a3c8fa9b298d5efdde23d` completed successfully after the verified News synthesis vertical and its acceptance regression.
- News now consumes the canonical latest synthesis in Flutter and exposes summary, importance, estimated impact, confidence and provenance while keeping the raw verified feed as an independent surface.
- The acceptance regression proves canonical transport, fail-closed parsing, FMP rejection, no recommendation/scoring/trading authority, 404 handling and stale-data removal after a 503/retry failure.
- News therefore moves conservatively from 65% to 75%, matching the rubric level for integrated functionality with meaningful tests; it does not move to 100% because broader E2E/UX and production model-execution/corroboration evidence remain open.
- Overall whole-product engineering completion moves conservatively from approximately 83% to approximately 84%.
- Operational readiness is tracked separately and does not increase from this UI/acceptance increment.
- No fixture, CI result or adapter presence is treated as proof of production data coverage, provider independence or model truth. Canonical market weighting remains human-controlled and automatic trading remains disabled.

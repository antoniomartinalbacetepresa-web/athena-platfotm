# ATHENA TYCHE — Engineering Completion Roadmap

Updated: 2026-09-11

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
| Datos / PIT / provenance / identity / FX | 96% |
| Analysis engines | 95% |
| Recommendation | 92% |
| Learning / validation | 88% |
| Portfolio / diversification | 95% |
| Investors / News | 84% |
| Flutter / UI | 90% |
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
| Core architecture & backend | 94% | FastAPI, repositories/services, database migrations, readiness diagnostics, authentication and encrypted owner-scoped profile persistence exist. Remaining: production hardening, protected merge gates and final cross-module acceptance. |
| Welcome & navigation | 90% | Welcome, account login/registration, guest mode, Dashboard, Market, News, Portfolio and Profile routes exist. Remaining: final end-to-end navigation/accessibility acceptance. |
| Dashboard | 85% | Responsive dashboard, live panels and operational readiness surface exist. Remaining: end-to-end states and final UX acceptance. |
| Market | 80% | Real persisted universe, regional ingestion, market-cap/canonical identity logic and standalone UI exist. Remaining: canonical weighting evidence, production coverage and deeper historical acceptance. |
| News | 65% | Verified backend feed and standalone reusable UI exist. Remaining: importance ranking, estimated impact and AI summary provenance. |
| Portfolio | 86% | Portfolio UI plus valuation, concentration, correlations, attribution/reconciliation and accounting infrastructure exist. Authenticated personal positions are isolated server-side by JWT-derived ownership. Flutter has a tested non-destructive sync bridge that transmits only symbol, exchange and quantity, explicitly excluding cost basis, current price, capital and owner identifiers. Remaining: wire the bridge into the complete Portfolio UX with explicit user controls, encrypted sensitive fields and final E2E acceptance. |
| Profile & authentication | 82% | Argon2 hashing, signed expiring JWT with unique jti/session version, register/token/me/logout/logout-all/change-password APIs, persistent token revocation, persistent login throttling, Flutter auth client support and guest mode exist. Profile now loads, edits, saves, reloads and deletes owner-scoped encrypted preferences through authenticated backend calls, with no insecure local fallback. Logout attempts remote token revocation before clearing the client session. Remaining: recovery with verified delivery channel, durable secure client session and broader account lifecycle acceptance. |
| ATHENA AI & recommendations | 78% | Research, catalysts, invalidation, factor risk, attribution, journal, devil's advocate, radar, shadow/OOS and diagnostics exist. Remaining: validated user-facing synthesis and longitudinal evidence thresholds. |
| Market history | 65% | Backfill, PIT preservation and depth-aware readiness gate exist. Remaining: real >=365-day eligible-universe coverage, source continuity and corporate-action acceptance. |
| Continuous learning | 70% | Calibration/drift/evaluation/shadow/OOS infrastructure exists. Remaining: sufficient real longitudinal OOS evidence and controlled promotion policy. |
| Personalization | 60% | Owner-scoped risk tolerance, investment horizon, base currency and objective have validated AES-256-GCM persistence, authenticated Flutter transport and a real Profile UI for load/save/reload/delete. SQLite stores ciphertext rather than those values in plaintext; tamper detection is tested and UI failures do not create an unsafe local copy. Remaining: richer questionnaire/adaptive personalization, encrypted capital/history where appropriate, key rotation/migration and final E2E acceptance. |
| Security & production hardening | 80% | Fail-closed auth secret, Argon2 hashes, signed expiring JWT, tamper checks, individual and all-session revocation, authenticated password rotation, resource-level portfolio authorization, persistent login rate limiting and authenticated AES-256-GCM profile encryption are validated. Encryption keys are externally supplied and never persisted in the profile table. Remaining: verified account recovery, durable secure client token storage, encryption-key rotation/management, backups, deployment secret management, threat-model acceptance and required branch checks. |
| Testing & CI | 95% | Backend pytest plus Flutter analyze/test validate pushed changes; auth revocation, all-session invalidation, password rotation, throttling, cross-user portfolio isolation, privacy-preserving portfolio sync, encrypted profile confidentiality/integrity and protected Profile preference form behavior have dedicated coverage. Remaining: mandatory protected-branch checks, broader E2E/security/recovery and release gates. |

**Overall whole-product engineering completion: approximately 79%.**

## Definition of 100%

ATHENA reaches 100% engineering completion only when every whole-product area above is at 100%, all mandatory CI/release gates pass, no critical blocker remains open, and documentation matches implemented behavior. A readiness diagnostic or analytical-core score reaching 100% does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish the authentication lifecycle: verified account recovery, secure durable client session and remaining account lifecycle controls.
2. Finish authenticated Portfolio integration and extend encrypted Profile personalization only with an explicit privacy contract; add richer questionnaire/adaptive behavior without insecure local persistence.
3. Add encryption-key rotation/migration, backup/recovery, threat-model and deployment-secret hardening.
4. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
5. Reach real historical depth/coverage and corporate-action-safe acceptance.
6. Close longitudinal OOS and forecast-error evidence gates without fabricated/synthetic production evidence.
7. Finish verified News impact/importance/AI-summary provenance and final ATHENA user-facing synthesis.
8. Make CI checks mandatory on protected branches and add E2E/security/release gates.
9. Re-audit every area against `MASTER_PROJECT.md`; only then mark 100%.

## Latest validated increment

- Functional SHA `866a9e2643e298b76bfccbf9db4d367a868b168f` connects encrypted Profile preferences to the real Flutter UI with load/save/reload/delete states and no unsafe local fallback.
- Profile logout now attempts backend token revocation before clearing the local session; remote failure still cannot trap the user in a stale client session.
- Widget regressions cover guest isolation, preference validation, normalization and reload behavior.
- GitHub Actions run `34540217848` passed Backend tests, Flutter analyze and Flutter tests for that exact functional SHA.

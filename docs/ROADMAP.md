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
| News | 65% | Verified backend feed and standalone reusable UI exist. Remaining: importance ranking, estimated impact and AI summary provenance. |
| Portfolio | 88% | Portfolio UI plus valuation, concentration, correlations, attribution/reconciliation and accounting infrastructure exist. Authenticated personal positions are isolated server-side by JWT-derived ownership. Flutter exposes a tested explicit authenticated sync action in the real Portfolio route using the non-destructive bridge; it transmits only symbol, exchange and quantity and excludes cost basis, current price, capital and owner identifiers. Remaining: encrypted sensitive fields where server persistence is justified and final E2E/UX acceptance. |
| Profile & authentication | 90% | Argon2 hashing, signed expiring JWT with unique jti/session version, register/token/me/logout/logout-all/change-password APIs, persistent token revocation, persistent login throttling, Flutter auth client support, guest mode and durable token persistence in platform secure storage exist. Account recovery has one-time cryptographic tokens stored only as SHA-256 digests, 30-minute expiry, persistent request throttling, configurable SMTP delivery that requires an HTTPS public recovery URL, password reset, token replay rejection and all-session invalidation after a successful reset. Flutter exposes a tested recovery flow from Login, preserves the generic anti-enumeration response, consumes the HTTPS recovery link token without durable token storage, mirrors backend token/password boundaries and requires a fresh login after reset. Restored access tokens are validated against `/auth/me`; invalid/stale tokens are removed instead of trusted locally. Profile loads, edits, saves, reloads and deletes owner-scoped encrypted preferences through authenticated backend calls, with no insecure local fallback. Remaining: verify the SMTP delivery channel in the real deployment and complete broader account-lifecycle/E2E acceptance. |
| ATHENA AI & recommendations | 78% | Research, catalysts, invalidation, factor risk, attribution, journal, devil's advocate, radar, shadow/OOS and diagnostics exist. Remaining: validated user-facing synthesis and longitudinal evidence thresholds. |
| Market history | 72% | One-year Yahoo history requests, PIT market observations, source-continuity depth diagnostics, corporate-action extraction/ingestion, immutable PIT storage, central schema v5 migration and cross-provider reconciliation diagnostics exist. Reconciliation never auto-selects a provider when values conflict or one source is absent. Remaining: measured real >=365-day eligible-universe coverage, an independent secondary corporate-action feed with measured agreement, source continuity and final adjustment/acceptance gates. |
| Continuous learning | 70% | Calibration/drift/evaluation/shadow/OOS infrastructure exists. Remaining: sufficient real longitudinal OOS evidence and controlled promotion policy. |
| Personalization | 65% | Owner-scoped risk tolerance, investment horizon, base currency and objective have validated AES-256-GCM persistence, authenticated Flutter transport and a real Profile UI for load/save/reload/delete. Profile encryption supports an explicit current key version, strict historical keyring, exact-version decrypt and transactional re-encryption to the current key; unknown/malformed key versions fail closed. Remaining: richer questionnaire/adaptive personalization, encrypted capital/history where appropriate, deployment key-management procedure and final E2E acceptance. |
| Security & production hardening | 90% | Fail-closed auth secret, Argon2 hashes, signed expiring JWT, tamper checks, individual and all-session revocation, authenticated password rotation, resource-level portfolio authorization, persistent login and recovery throttling, durable secure client token storage and authenticated AES-256-GCM profile encryption are validated. Password recovery tokens are random, one-use, expiring and persisted only as SHA-256 digests; successful reset rotates the password and revokes all prior sessions. SMTP recovery delivery is fail-closed unless explicitly configured with an HTTPS public recovery URL. Versioned profile-key rotation/migration is transactional and tested. Database backup/recovery uses SQLite's backup API for WAL-safe snapshots, SHA-256 manifests, `PRAGMA integrity_check`, schema-version validation, non-destructive restore semantics, fail-closed retention and a verified ephemeral restore drill exposed through the operator CLI. Remaining: real deployment verification of recovery delivery, deployment secret management, real scheduled/off-site backup operation, threat-model acceptance and required branch checks. |
| Testing & CI | 97% | Backend pytest plus Flutter analyze/test validate pushed changes; auth revocation, all-session invalidation, password rotation, login/recovery throttling, one-time password recovery, recovery replay rejection, Flutter recovery routing/reset UX, secure token restoration, cross-user portfolio isolation, privacy-preserving Portfolio sync, encrypted profile confidentiality/integrity, profile key rotation/rollback, protected Profile preference form behavior, corporate-action schema/ingestion/reconciliation and backup/verify/restore/retention/restore-drill safety have dedicated coverage. Remaining: mandatory protected-branch checks, broader E2E/security/recovery-delivery and release gates. |

**Overall whole-product engineering completion: approximately 82%.**

## Definition of 100%

ATHENA reaches 100% engineering completion only when every whole-product area above is at 100%, all mandatory CI/release gates pass, no critical blocker remains open, and documentation matches implemented behavior. A readiness diagnostic or analytical-core score reaching 100% does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish the authentication lifecycle: verify the configured recovery-delivery channel in the real deployment and complete remaining account-lifecycle/E2E controls.
2. Finish authenticated Portfolio acceptance and extend encrypted Profile personalization only with an explicit privacy contract; add richer questionnaire/adaptive behavior without insecure local persistence.
3. Complete production recovery operations: real scheduled/off-site backups, deployment key/secret management and threat-model acceptance; keep historical encryption keys only for the migration window and remove them after all rows have been re-encrypted and verified.
4. Reach real historical depth/coverage, connect an independent secondary corporate-action source and require reconciliation/adjustment quality gates before treating history as production-ready.
5. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
6. Close longitudinal OOS and forecast-error evidence gates without fabricated/synthetic production evidence.
7. Finish verified News impact/importance/AI-summary provenance and final ATHENA user-facing synthesis.
8. Make CI checks mandatory on protected branches and add E2E/security/release gates.
9. Re-audit every area against `MASTER_PROJECT.md`; only then mark 100%.

## Latest validated increment

- Start-of-run SHA `e994d3ce0b11cb8347ed4f8ffbd36bb71680f6c2` already contained the user-facing Flutter recovery flow and central corporate-action schema v5 work; its validation was still running when this execution began.
- Functional SHA `33ffd61bd6bfd3a1b4681b1546b96ba3bd7ac394` adds `CorporateActionReconciliationService`, which compares only PIT-visible corporate actions from two or more distinct providers at the same knowledge cutoff.
- The reconciliation service selects only the latest visible snapshot per provider/event for comparison, reports agreed/conflict/incomplete states, and never auto-canonicalizes a disputed or missing-source action.
- Test SHA `0431972e04c5cbc2bb31c10455464bafba4286c0` adds regressions for identical dividends/splits, conflicting values, missing providers, latest-snapshot selection, invalid persisted contracts, duplicate-provider rejection and timezone-aware PIT cutoffs.
- GitHub Actions run `34587965588` passed Backend tests, Flutter analyze and Flutter tests for exact SHA `0431972e04c5cbc2bb31c10455464bafba4286c0`.
- Profile/authentication is 90%, Flutter/UI rises conservatively from 90% to 91%, and Market history from 65% to 72% because the previously pending recovery UX and the corporate-action schema/ingestion/reconciliation chain are implemented and validated. Whole-product completion rises conservatively from approximately 81% to approximately 82%.
- None of this proves real SMTP delivery, real >=365-day eligible-universe coverage, or independent secondary-source corporate-action agreement in production. Those acceptance items remain open and must not be inferred from CI fixtures.

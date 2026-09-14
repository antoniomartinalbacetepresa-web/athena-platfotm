# ATHENA TYCHE — Engineering Completion Roadmap

Updated: 2026-09-14

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
| Portfolio | 88% | Portfolio UI plus valuation, concentration, correlations, attribution/reconciliation and accounting infrastructure exist. Authenticated personal positions are isolated server-side by JWT-derived ownership. Declared average purchase price is persisted with AES-256-GCM and synchronized only through authenticated transport. The owner-scoped append-only Event Ledger is exposed through an authenticated read-only history API with PIT `asOf` filtering; A/B regression proves that equal logical `portfolioId` values do not cross account boundaries. Flutter now consumes that same ledger through a typed fail-closed model and exposes loading, empty, error/retry and event-list states from the authenticated Portfolio entry point without creating a second history store. Remaining: broader Portfolio E2E/UX acceptance and production key-management evidence. |
| Profile & authentication | 90% | Argon2 hashing, signed expiring JWT with unique jti/session version, register/token/me/logout/logout-all/change-password APIs, persistent token revocation, persistent login throttling, Flutter auth client support, guest mode and durable token persistence in platform secure storage exist. Account recovery has one-time cryptographic tokens stored only as SHA-256 digests, 30-minute expiry, persistent request throttling, configurable SMTP delivery that requires an HTTPS public recovery URL, password reset, token replay rejection and all-session invalidation after a successful reset. Flutter exposes a tested recovery flow from Login, preserves the generic anti-enumeration response, consumes the HTTPS recovery link token without durable token storage, mirrors backend token/password boundaries and requires a fresh login after reset. Restored access tokens are validated against `/auth/me`; invalid/stale tokens are removed instead of trusted locally. Profile loads, edits, saves, reloads and deletes owner-scoped encrypted preferences through authenticated backend calls, with no insecure local fallback. Remaining: verify the SMTP delivery channel in the real deployment and complete broader account-lifecycle/E2E acceptance. |
| ATHENA AI & recommendations | 78% | Research, catalysts, invalidation, factor risk, attribution, journal, devil's advocate, radar, shadow/OOS and diagnostics exist. Remaining: validated user-facing synthesis and longitudinal evidence thresholds. |
| Market history | 72% | One-year Yahoo history requests, PIT market observations, source-continuity depth diagnostics, corporate-action extraction/ingestion, immutable PIT storage, central schema v5 migration and cross-provider reconciliation diagnostics exist. Reconciliation never auto-selects a provider when values conflict or one source is absent. Remaining: measured real >=365-day eligible-universe coverage, an independent secondary corporate-action feed with measured agreement, source continuity and final adjustment/acceptance gates. |
| Continuous learning | 70% | Calibration/drift/evaluation/shadow/OOS infrastructure exists. Remaining: sufficient real longitudinal OOS evidence and controlled promotion policy. |
| Personalization | 75% | Owner-scoped risk tolerance, investment horizon, base currency, objective, experience level, liquidity need, maximum drawdown tolerance and available capital have validated AES-256-GCM persistence, authenticated Flutter transport and Profile UI load/save/reload/delete. The richer questionnaire feeds a deterministic presentation-only personalization projection and an authenticated owner-scoped readiness diagnostic; both exclude sensitive monetary/currency values and explicitly cannot influence recommendation scoring, canonical weighting, automatic learning promotion or trading. Acceptance coverage proves incomplete-to-complete questionnaire transitions, adaptive presentation, privacy invariants and deletion semantics. Profile encryption supports explicit key versions, strict historical keyring, exact-version decrypt and transactional re-encryption; unknown/malformed key versions fail closed. Authenticated Portfolio also persists declared average purchase price encrypted without treating it as trading authority. Remaining: deployment key-management procedure, broader cross-surface E2E/UX acceptance and production operational evidence. |
| Security & production hardening | 92% | Fail-closed auth secret, Argon2 hashes, signed expiring JWT, tamper checks, individual and all-session revocation, authenticated password rotation, resource-level portfolio authorization, persistent login and recovery throttling, durable secure client token storage and authenticated AES-256-GCM profile encryption are validated. Password recovery tokens are random, one-use, expiring and persisted only as SHA-256 digests; successful reset rotates the password and revokes all prior sessions. SMTP recovery delivery is fail-closed unless explicitly configured with an HTTPS public recovery URL. Versioned profile-key rotation/migration is transactional and tested. Database backup/recovery uses SQLite's backup API for WAL-safe snapshots, SHA-256 manifests, `PRAGMA integrity_check`, schema-version validation, non-destructive restore semantics, fail-closed retention and a verified ephemeral restore drill exposed through the operator CLI. Owner-scoped portfolio history reuses the append-only hash-chained ledger rather than duplicating history into a weaker store. Sensitive auth/user responses are marked no-store. A documented v1 threat model now defines assets, trust boundaries, threats, controls and explicitly unresolved production evidence. `/api/v1/readiness/security` performs fail-closed deployment checks for auth-secret strength, AES-256 profile-key shape/versioning, historical-keyring validity, auth/profile key separation, HTTPS recovery URL, SMTP endpoint/credential coherence and STARTTLS, while never returning secret values or claiming production deployment/SMTP/off-site-backup verification. Remaining: real deployment verification of recovery delivery, secret-manager custody/rotation evidence, real scheduled/off-site backup operation, operational incident-response acceptance and required branch checks. |
| Testing & CI | 97% | Backend pytest plus Flutter analyze/test validate pushed changes; auth revocation, all-session invalidation, password rotation, login/recovery throttling, one-time password recovery, recovery replay rejection, Flutter recovery routing/reset UX, secure token restoration, cross-user portfolio isolation, encrypted average purchase price, owner-scoped PIT portfolio-history isolation, typed Flutter portfolio-history parsing/transport/UI states, encrypted profile confidentiality/integrity, richer personalization readiness/adaptation/privacy/deletion, profile key rotation/rollback, protected Profile preference form behavior, deployment secret/key/TLS readiness and no-disclosure guarantees, corporate-action schema/ingestion/reconciliation and backup/verify/restore/retention/restore-drill safety have dedicated coverage. Remaining: mandatory protected-branch checks, broader E2E/security/recovery-delivery and release gates. |

**Overall whole-product engineering completion: approximately 83%.**

## Definition of 100%

ATHENA reaches 100% engineering completion only when every whole-product area above is at 100%, all mandatory CI/release gates pass, no critical blocker remains open, and documentation matches implemented behavior. A readiness diagnostic or analytical-core score reaching 100% does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish the authentication lifecycle: verify the configured recovery-delivery channel in the real deployment and complete remaining account-lifecycle/E2E controls.
2. Finish authenticated Portfolio acceptance and encrypted Profile personalization with broader cross-surface E2E/UX acceptance while preserving the explicit privacy/no-authority contract and avoiding insecure local persistence.
3. Complete production recovery operations: real scheduled/off-site backups, deployment secret-manager custody/rotation and operational incident-response acceptance; keep historical encryption keys only for the migration window and remove them after all rows have been re-encrypted and verified.
4. Reach real historical depth/coverage, connect an independent secondary corporate-action source and require reconciliation/adjustment quality gates before treating history as production-ready.
5. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
6. Close longitudinal OOS and forecast-error evidence gates without fabricated/synthetic production evidence.
7. Finish verified News impact/importance/AI-summary provenance and final ATHENA user-facing synthesis.
8. Make CI checks mandatory on protected branches and add E2E/security/release gates.
9. Re-audit every area against `MASTER_PROJECT.md`; only then mark 100%.

## Latest validated increment

- Start-of-run SHA `631ce8a66f111f5690aa5db98052e19cac2fa2bf` had four successful exact-SHA Backend/Flutter checks and already contained no-store handling for sensitive auth/user responses.
- SHA `4145ae9444bd591e4bff4d2215b165c4ef5efde1` adds fail-closed deployment security readiness checks without exposing secret material.
- SHA `bb179e7e82712188309b40443ffbb6a442c0c6c8` exposes those checks through read-only `/api/v1/readiness/security` without granting production authority.
- SHA `03bfd160dde31df267d96f9334926b2b07fc3009` adds regressions for missing/reused secrets, invalid historical keyrings, insecure recovery/TLS, coherent secure configuration and secret non-disclosure.
- SHA `bf0b5c7b0f0a0894c7bdfc0d61d60cf2957ec332` documents the v1 threat model, assets, trust boundaries, implemented controls and operational evidence that remains explicitly unproven. All four exact-SHA Backend/Flutter checks passed.
- Security & production hardening moves from 90% to 92% because the remaining threat-model/configuration-validation gap is now integrated, documented and regression-tested. It does not move higher because secret-manager custody/rotation, real SMTP delivery, real scheduled/off-site backup execution, operational incident-response and required branch checks remain unverified.
- Overall whole-product engineering completion remains approximately 83%; this security increment is material but not large enough to justify rounding the aggregate to 84% conservatively.
- None of this proves production secret custody, SMTP delivery, off-site backups, real >=365-day eligible-universe coverage, independent secondary-source corporate-action agreement or operational release enforcement. Those acceptance items remain open and must not be inferred from CI fixtures.

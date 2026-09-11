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
| Core architecture & backend | 94% | FastAPI, repositories/services, database migrations, readiness diagnostics, authentication, encrypted owner-scoped profile persistence and verified SQLite backup/recovery services exist. Remaining: production hardening, protected merge gates and final cross-module acceptance. |
| Welcome & navigation | 90% | Welcome, account login/registration, guest mode, Dashboard, Market, News, Portfolio and Profile routes exist. Remaining: final end-to-end navigation/accessibility acceptance. |
| Dashboard | 85% | Responsive dashboard, live panels and operational readiness surface exist. Remaining: end-to-end states and final UX acceptance. |
| Market | 80% | Real persisted universe, regional ingestion, market-cap/canonical identity logic and standalone UI exist. Remaining: canonical weighting evidence, production coverage and deeper historical acceptance. |
| News | 65% | Verified backend feed and standalone reusable UI exist. Remaining: importance ranking, estimated impact and AI summary provenance. |
| Portfolio | 88% | Portfolio UI plus valuation, concentration, correlations, attribution/reconciliation and accounting infrastructure exist. Authenticated personal positions are isolated server-side by JWT-derived ownership. Flutter now exposes a tested explicit authenticated sync action in the real Portfolio route using the non-destructive bridge; it transmits only symbol, exchange and quantity and excludes cost basis, current price, capital and owner identifiers. Remaining: encrypted sensitive fields where server persistence is justified and final E2E/UX acceptance. |
| Profile & authentication | 85% | Argon2 hashing, signed expiring JWT with unique jti/session version, register/token/me/logout/logout-all/change-password APIs, persistent token revocation, persistent login throttling, Flutter auth client support, guest mode and durable token persistence in platform secure storage exist. Restored tokens are validated against `/auth/me`; invalid/stale tokens are removed instead of trusted locally. Profile loads, edits, saves, reloads and deletes owner-scoped encrypted preferences through authenticated backend calls, with no insecure local fallback. Remaining: recovery with a verified delivery channel and broader account-lifecycle/E2E acceptance. |
| ATHENA AI & recommendations | 78% | Research, catalysts, invalidation, factor risk, attribution, journal, devil's advocate, radar, shadow/OOS and diagnostics exist. Remaining: validated user-facing synthesis and longitudinal evidence thresholds. |
| Market history | 65% | Backfill, PIT preservation and depth-aware readiness gate exist. Remaining: real >=365-day eligible-universe coverage, source continuity and corporate-action acceptance. |
| Continuous learning | 70% | Calibration/drift/evaluation/shadow/OOS infrastructure exists. Remaining: sufficient real longitudinal OOS evidence and controlled promotion policy. |
| Personalization | 65% | Owner-scoped risk tolerance, investment horizon, base currency and objective have validated AES-256-GCM persistence, authenticated Flutter transport and a real Profile UI for load/save/reload/delete. Profile encryption now supports an explicit current key version, strict historical keyring, exact-version decrypt and transactional re-encryption to the current key; unknown/malformed key versions fail closed. Remaining: richer questionnaire/adaptive personalization, encrypted capital/history where appropriate, deployment key-management procedure and final E2E acceptance. |
| Security & production hardening | 89% | Fail-closed auth secret, Argon2 hashes, signed expiring JWT, tamper checks, individual and all-session revocation, authenticated password rotation, resource-level portfolio authorization, persistent login rate limiting, durable secure client token storage and authenticated AES-256-GCM profile encryption are validated. Versioned profile-key rotation/migration is transactional and tested. Database backup/recovery uses SQLite's backup API for WAL-safe snapshots, SHA-256 manifests, `PRAGMA integrity_check`, schema-version validation, non-destructive restore semantics, fail-closed retention and a verified ephemeral restore drill exposed through the operator CLI. Remaining: verified account recovery, deployment secret management, real scheduled/off-site backup operation, threat-model acceptance and required branch checks. |
| Testing & CI | 97% | Backend pytest plus Flutter analyze/test validate pushed changes; auth revocation, all-session invalidation, password rotation, throttling, secure token restoration, cross-user portfolio isolation, privacy-preserving Portfolio sync, encrypted profile confidentiality/integrity, profile key rotation/rollback, protected Profile preference form behavior and backup/verify/restore/retention/restore-drill safety have dedicated coverage. Remaining: mandatory protected-branch checks, broader E2E/security/recovery and release gates. |

**Overall whole-product engineering completion: approximately 81%.**

## Definition of 100%

ATHENA reaches 100% engineering completion only when every whole-product area above is at 100%, all mandatory CI/release gates pass, no critical blocker remains open, and documentation matches implemented behavior. A readiness diagnostic or analytical-core score reaching 100% does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish the authentication lifecycle: verified account recovery and remaining account-lifecycle controls.
2. Finish authenticated Portfolio acceptance and extend encrypted Profile personalization only with an explicit privacy contract; add richer questionnaire/adaptive behavior without insecure local persistence.
3. Complete production recovery operations: real scheduled/off-site backups, deployment key/secret management and threat-model acceptance; keep historical encryption keys only for the migration window and remove them after all rows have been re-encrypted and verified.
4. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
5. Reach real historical depth/coverage and corporate-action-safe acceptance.
6. Close longitudinal OOS and forecast-error evidence gates without fabricated/synthetic production evidence.
7. Finish verified News impact/importance/AI-summary provenance and final ATHENA user-facing synthesis.
8. Make CI checks mandatory on protected branches and add E2E/security/release gates.
9. Re-audit every area against `MASTER_PROJECT.md`; only then mark 100%.

## Latest validated increment

- Start-of-run SHA `621c233b4da231c2fb338cdd904c7a5ba0b30f18` had GitHub Actions run `34556750233` fully green before this increment.
- Functional SHA `202f0b30eb90ca65216e6aded87fce8de2da5ea1` adds a verified restore drill to the existing SQLite backup/recovery service and exposes it through `backend/scripts/database_backup.py drill`.
- The drill first verifies the backup manifest/checksum/integrity, restores into an isolated temporary directory, validates the restored ATHENA schema/integrity again, and deletes the temporary restoration automatically. It refuses to use the active database directory as its working directory.
- Dedicated regressions prove successful restore-and-cleanup, rejection of tampered backups without leftover drill artifacts, active-database-directory protection and the CLI flow.
- GitHub Actions run `34560905169` passed Backend tests, Flutter analyze and Flutter tests for that exact functional SHA.
- Previously validated authenticated Portfolio routing is now reflected in the score/evidence instead of remaining incorrectly listed as unwired.
- These tests prove software behavior in CI; they do **not** prove that production backups are scheduled, stored off-site or recoverable under a real disaster. Those operational controls remain open.

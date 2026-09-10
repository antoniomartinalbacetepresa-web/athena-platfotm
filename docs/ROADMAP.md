# ATHENA TYCHE — Engineering Completion Roadmap

Updated: 2026-09-10

This roadmap measures software completion against `docs/MASTER_PROJECT.md`. It does not measure investment performance, predictive skill, profitability, or production authorization.

## Scoring rubric

- **0%**: absent.
- **25%**: scaffold/data model exists.
- **50%**: functional UI or service exists.
- **75%**: integrated with real data and covered by meaningful tests.
- **100%**: acceptance criteria complete, production-safe for its intended scope, and CI green.

Percentages are conservative engineering estimates. They may move down if an audit discovers missing acceptance criteria or unsafe assumptions.

## Current audited baseline

| Area | Progress | Current evidence / remaining work |
| --- | ---: | --- |
| Core architecture & backend | 90% | FastAPI backend, repositories/services, database layer and many sealed/auditable recommendation modules exist. Remaining: production hardening and final cross-module acceptance. |
| Welcome & navigation | 75% | Welcome, Dashboard, Portfolio and Profile routes exist. Remaining: complete first-class navigation for all V1 surfaces and navigation tests. |
| Dashboard | 80% | Responsive dashboard and live market/recommendation/news panels exist. Remaining: complete readiness/status integration and end-to-end acceptance. |
| Market | 75% | Real persisted universe, Yahoo regional ingestion, canonical issuer/market-cap logic and market UI exist. Remaining: canonical weighting blockers, standalone navigation/experience and full historical depth. |
| News | 50% | Models/repositories/services and Dashboard news surface exist. Remaining: standalone V1 news experience, impact/importance acceptance and AI summary provenance. |
| Portfolio | 80% | Portfolio UI and substantial backend accounting/reconciliation/attribution infrastructure exist. Remaining: end-to-end user flows, persistence/security acceptance and production-quality UX. |
| Profile | 50% | Profile page, route and widget test exist. Remaining: secure user identity, settings persistence, risk-profile workflow, privacy controls and backend contract. |
| ATHENA AI & recommendations | 70% | Recommendation research, catalysts, devil's advocate, radar, attribution, shadow/OOS and diagnostics exist. Remaining: validated user-facing synthesis, explainability acceptance and evidence thresholds before any production claims. |
| Market history | 60% | Market observations, backfill tooling and coverage diagnostics exist. Remaining: required horizon depth, source continuity, corporate-action correctness and historical acceptance gates. |
| Continuous learning | 70% | Performance, calibration, drift, evaluation schedules, shadow-live, OOS cohorts and forecast-error diagnostics exist. Remaining: sufficient longitudinal evidence and controlled update policy; automatic mutation remains forbidden. |
| Personalization | 25% | Product requirement exists and Profile surface has begun. Remaining: secure per-user state, capital/objectives/risk/history contracts and privacy-aware persistence. |
| Security & production hardening | 55% | Conservative no-advice/no-auto-trading gates, tamper checks, append-only evidence patterns and restricted local CORS exist. Remaining: authentication, authorization, encrypted sensitive storage, backup/recovery, secrets/deployment hardening and threat-model acceptance. |
| Testing & CI | 90% | GitHub Actions runs backend pytest plus Flutter analyze/test on the development branch. Remaining: broader end-to-end/integration/security tests and production release gates. |

**Overall engineering completion: 67%** (equal-weight baseline across the 13 audited areas).

## Definition of 100%

ATHENA reaches 100% engineering completion only when every area above is at 100%, all mandatory CI/release gates pass, no critical blocker is open, and documentation matches the implemented behavior. A readiness diagnostic reaching 100% in one subsystem does **not** mean the whole product is complete.

## Highest-priority path to 100%

1. Finish V1 product surfaces and navigation: Market, News, Profile, Portfolio and Dashboard acceptance.
2. Close canonical market-weighting structural blockers without lowering thresholds; external approval remains human-controlled.
3. Establish required historical-depth gates and corporate-action-safe history.
4. Complete secure authentication/personalization storage before persisting sensitive profile data.
5. Close longitudinal OOS/forecast-error evidence gates before enabling any learning promotion.
6. Add end-to-end, security, recovery and release tests.
7. Re-audit every area against acceptance criteria; only then mark 100%.

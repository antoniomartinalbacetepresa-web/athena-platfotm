# Auditable acceptance inventory — initial baseline (2026-11-05)

Scope: `docs/MASTER_PROJECT.md` and `docs/ROADMAP.md`. This is a **partial seed**, not a complete inventory or certified progress report. Historical 91%/85% estimates are not certified current scores. All entries below remain **pending verification**; an existing implementation, test or CI pass alone does not establish operational acceptance.

## Evidence and scoring contract

Each criterion has a stable ID, one exclusive accounting area, module, observable acceptance, dependency, weight, state, evidence and blocker. Weight 3 = critical user-facing safety/data path; 2 = important product workflow; 1 = supporting/future capability. A criterion advances only with an exact SHA and test/operational evidence, verified data licensing and PIT where applicable. States: pending; implemented+CI; integrated with real data; validated in authorized deployment; blocked. The nominal weighted operational acceptance formula, **only after the inventory covers all roadmap/master scope and gates are independently verified**, is `100 * sum(weight of operationally accepted criteria) / sum(weight of all criteria)`. Intermediate implementation/CI cannot count as operational acceptance; no fractional credit for fixtures. 100% additionally requires all mandatory release/security/real-data gates. Until scope coverage and evidence are complete, **percentage current not certifiable** for either area.

| ID | Area | Module | Observable acceptance | Dependency | Weight | State | Evidence | Blocker |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| CORE-001 | Analytical core | Market data/PIT | One selected liquid instrument has 365-day legally usable, timestamped price history with gaps, corporate actions and independent reconciliation exposed | Licensed providers | 3 | blocked | Not yet verified at an exact SHA | License, operational coverage and reconciliation |
| CORE-002 | Analytical core | Research cycle | Real Market + News evidence is bound PIT to a persisted canonical research cycle with idempotent retrieval | CORE-001 and licensed news | 3 | pending | Not yet verified at an exact SHA | End-to-end real-clock test |
| CORE-003 | Analytical core | Risk/valuation | Human-readable risk, valuation and uncertainty derived only from accepted evidence | CORE-002 | 3 | pending | Not yet verified at an exact SHA | Real evidence and OOS |
| CORE-004 | Analytical core | Opportunity & Exit Radar | Volume/RVOL, liquidity and invalidation explanations show provenance and no automated orders | CORE-001 | 2 | pending | Not yet verified at an exact SHA | Licensed adjusted volume, OOS and costs |
| CORE-005 | Analytical core | Learning | Precommitted predictions pass longitudinal OOS and walk-forward evaluation | CORE-003 | 3 | pending | Not yet verified at an exact SHA | Longitudinal observations |
| PRODUCT-001 | Whole product | Market/News/ATHENA | Select instrument in Flutter and see licensed real prices, news, persisted analysis, dates, staleness and error states | CORE-001 through CORE-003 | 3 | pending | Not yet verified at an exact SHA | Authorized E2E deployment |
| PRODUCT-002 | Whole product | Dashboard/Investors | Consistent provenance-bound read-only research across screens | PRODUCT-001 | 2 | pending | Not yet verified at an exact SHA | Cross-surface E2E |
| PRODUCT-003 | Whole product | Profile/Portfolio | Authenticated owner isolation, encrypted preferences and accessible cross-surface navigation | Deployment keys and auth | 3 | pending | Not yet verified at an exact SHA | Deployment and accessibility acceptance |
| PRODUCT-004 | Whole product | Security/operations | Mandatory CI, recovery delivery, secret custody, backup/restore and incident response validated in deployment | Authorized deployment | 3 | blocked | Not yet verified at an exact SHA | External operational evidence |
| PRODUCT-005 | Whole product | Future broker adapter | Provider-neutral paper-only interface, IBKR pilot adapter and future execution controls kept disabled until separate authorization | Legal review, broker agreement and OOS | 2 | pending | Not yet verified at an exact SHA | Future phase, no live execution authorization |

## Scope coverage gap (mandatory follow-up)

The table is **not exhaustive**. Extend stable IDs without replacing these: ETFs/indices/commodities/FX/crypto, news filtering, alerts, journal, catalysts, factor risk, attribution, historical crises, portfolio accounting, onboarding, languages, personalization, community, ML, UX/accessibility, backups and all remaining modules in both source documents. Avoid double counting: CORE IDs measure analytical evidence; PRODUCT IDs measure user-visible integration and operational readiness. Do not publish numeric completion until a documented module-by-module coverage review reconciles every source heading and acceptance criterion.

Current certified completion — analytical core: **not certifiable**; whole product: **not certifiable**. This file does not change any functional or production claim.

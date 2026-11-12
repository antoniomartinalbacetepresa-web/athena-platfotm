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

## Additional acceptance criteria — scope reconciliation in progress (2026-11-06)

The following entries expand coverage without claiming implementation, CI success, licensed data or operational readiness. They preserve future phases from the master plan. A future review must split any criterion that proves too broad before certification.

| ID | Area | Module | Observable acceptance | Dependency | Weight | State | Evidence | Blocker |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| CORE-006 | Analytical core | Multi-asset identity | Stocks, ETFs, indices, commodities, FX and crypto are identified unambiguously with currency, venue and asset-class boundaries | Licensed asset-specific sources | 3 | pending | Not verified | Source rights, cross-asset contract |
| CORE-007 | Analytical core | Historical regimes | Historical bull/bear markets and crises are compared with PIT-safe, survivorship-aware samples | CORE-001 | 2 | pending | Not verified | Historical licensed depth |
| CORE-008 | Analytical core | Fundamentals/macro | Earnings, valuation inputs and macro releases carry publication and available-at timestamps and revisions | Licensed PIT fundamentals/macro | 3 | pending | Not verified | Source rights and revision history |
| CORE-009 | Analytical core | Research explanations | Journal, catalysts, thesis invalidation and devil's advocate cite immutable contradictory evidence | CORE-002 | 2 | pending | Not verified | Real persisted cycles |
| CORE-010 | Analytical core | Factor/attribution | Factor exposure, scenario asymmetry, reverse valuation and performance attribution use consistent provenance and FX | CORE-003 | 2 | pending | Not verified | Real reconciled inputs |
| CORE-011 | Analytical core | Predictions/calibration | Probability estimates are calibrated and reported with uncertainty, regime splits and precommitted evaluation | CORE-005 | 3 | pending | Not verified | Longitudinal OOS |
| CORE-012 | Analytical core | Volume execution realism | RVOL 20/50, OBV, breakouts and liquidity hypotheses include adjusted sessions, spreads, slippage and false positives; VWAP only with licensed intraday bars | CORE-004 | 3 | pending | Not verified | Licensed volume and OOS |
| CORE-013 | Analytical core | Continuous learning | Controlled model promotion has rollback, drift checks and no unsupervised authority over investment decisions | CORE-005 | 3 | pending | Not verified | Promotion policy and operational audit |
| CORE-014 | Analytical core | News/Investors synthesis | News importance, investor evidence and sentiment are corroborated, PIT-bound and never treated as price feeds | CORE-002 | 2 | pending | Not verified | Real-source corroboration |
| PRODUCT-006 | Whole product | Welcome/navigation | Welcome, onboarding and responsive navigation remain accessible across compact and wide layouts | Flutter E2E | 2 | pending | Not verified | Cross-device accessibility |
| PRODUCT-007 | Whole product | Asset coverage | Market screens expose asset-class coverage, source gaps and unsupported cases without fabricated quotes | CORE-006 | 3 | pending | Not verified | Multi-asset licensed feeds |
| PRODUCT-008 | Whole product | News/alerts | Filtered news, impact uncertainty and opt-in alerts expose publication times and non-advisory boundaries | CORE-014 | 2 | pending | Not verified | Notification permission and real E2E |
| PRODUCT-009 | Whole product | Portfolio accounting | Positions, average cost, P/L, total return, dividends, FX, reconciliation and history are consistent and owner-scoped | PRODUCT-003 | 3 | pending | Not verified | Cross-surface authenticated E2E |
| PRODUCT-010 | Whole product | Profile/localization | User preferences, risk context and Spanish UI work; future English, French, Portuguese, Italian, German, Russian and other languages remain in scope | PRODUCT-003 | 2 | pending | Not verified | Translation and UX acceptance |
| PRODUCT-011 | Whole product | ATHENA explanations | Charts, macro, technical/fundamental factors and AI explanation display uncertainty and source links; Ollama unavailable state is nonblocking | CORE-003, CORE-008 | 3 | pending | Not verified | Authorized model and UI E2E |
| PRODUCT-012 | Whole product | Learning presentation | Forecast history, calibration, drift and model limitations are readable without claiming investment performance | CORE-011 | 2 | pending | Not verified | Longitudinal validation |
| PRODUCT-013 | Whole product | Community/future comparison | Future community and investor comparisons enforce consent, moderation, privacy and non-advisory boundaries | Privacy design | 1 | pending | Not verified | Future phase |
| PRODUCT-014 | Whole product | Local Windows operation | Restart recovery, bounded CPU/RAM, secure SSD persistence, offline states and optional on-demand Ollama work on supported Windows | Security and load tests | 3 | pending | Not verified | Hardware measurements |
| PRODUCT-015 | Whole product | Portable secure deployment | Authorized Windows/Linux deployment verifies backups, restore, access isolation, secrets and operational incident handling | PRODUCT-004 | 3 | pending | Not verified | Authorized infrastructure |
| PRODUCT-016 | Whole product | Future broker safety | Paper-only IBKR adapter validates disconnect/reconnect, reconciliation, idempotency and kill switch; live orders remain disabled pending separate explicit authorization | PRODUCT-005 | 3 | pending | Not verified | Broker contractual review and paper tests |


## Approved competitive capabilities — pending verification (2026-11-12)

These IDs preserve the twelve approved improvements. XTrend Lite overlap is not counted twice. Weight 3 = financial safety/critical integration, 2 = user-facing capability, 1 = supporting visualization. No acceptance score increases.

| ID | Area | Module | Observable acceptance | Dependency | Weight | State | Evidence | Blocker |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| PRODUCT-017 | Whole product | Company dossier | Cross-screen licensed PIT dossier with prices, volume, fundamentals, risks and error states | CORE-001/002/003 | 3 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-018 | Whole product | Opportunity screener | Auditable price, RVOL, liquidity, valuation and risk filters | CORE-001/012 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-019 | Whole product | Alerts | Human-configured price, volume, breakout, 25-session low and earnings alerts without orders | CORE-004/008 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-020 | Whole product | Paper risk simulator | Costs, liquidity, exposure, drawdown and benchmark for hypothetical positions | CORE-003/012 | 3 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-021 | Whole product | Event calendar | Authorized deduplicated economic and corporate events with timezone and availableAt | CORE-008 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-022 | Whole product | Portfolio analytics | Reconciled concentration, sector, region, benchmark and volatility | PRODUCT-009 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-023 | Whole product | Peer comparator | Comparable valuation, debt, margins and dividend metrics with FX and period warnings | CORE-008 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-024 | Whole product | Strategy lab | Precommitted 25-session rebound and other hypotheses tested OOS with costs and failed firms | CORE-005/007/012 | 3 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-025 | Whole product | Sector heatmap | Licensed PIT sector heatmap and rotation with missing-data states | CORE-006 | 1 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-026 | Whole product | Official insiders | Official filing-linked insider activity with availableAt and no causal claims | CORE-008 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-027 | Whole product | Return and tax breakdown | Separate price, dividend, FX and cost return; verified Spanish tax only | PRODUCT-009 | 3 | pending | Not verified | Licensed real-clock E2E and deployment evidence |
| PRODUCT-028 | Whole product | Contradiction detector | PIT-supported and opposing price, volume, earnings, liquidity and news evidence | CORE-003/014 | 2 | pending | Not verified | Licensed real-clock E2E and deployment evidence |

## Scope coverage gap (mandatory follow-up)

The table is **not exhaustive**. Extend stable IDs without replacing these: ETFs/indices/commodities/FX/crypto, news filtering, alerts, journal, catalysts, factor risk, attribution, historical crises, portfolio accounting, onboarding, languages, personalization, community, ML, UX/accessibility, backups and all remaining modules in both source documents. Avoid double counting: CORE IDs measure analytical evidence; PRODUCT IDs measure user-visible integration and operational readiness. Do not publish numeric completion until a documented module-by-module coverage review reconciles every source heading and acceptance criterion.

Current certified completion — analytical core: **not certifiable**; whole product: **not certifiable**. This file does not change any functional or production claim.

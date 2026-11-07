# ATHENA TYCHE — Acceptance evidence register (baseline, NOT a completion claim)

Source of scope: `docs/MASTER_PROJECT.md`, `docs/ROADMAP.md` (historical estimates only). This register is an **initial audit seed**, not a complete inventory. Any unlisted requirement remains in scope. No percentage is certifiable until the entire scope has been decomposed, independently reviewed, and each applicable item has evidence.

Status vocabulary: `pending`, `implemented+CI`, `integrated-real-data`, `validated-authorized-deployment`, `blocked`. **All items below remain pending** pending evidence audit. A green synthetic test is not proof of real-data operation. No evidence is inherited from historical roadmap percentages.

| ID | Area | Module | Observable acceptance | Dependency | Weight | Status | Evidence | Blocker |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| CORE-001 | Core | Instrument identity | Selected ticker resolves to canonical issuer/exchange identity | Authorized provider | 3 | pending | none audited | identity agreement |
| CORE-002 | Core | Prices | Timestamped licensed prices, gaps and 365-day depth visible | Provider rights | 5 | pending | none audited | rights/coverage |
| CORE-003 | Core | Corporate actions/FX | Splits, dividends and FX adjustments independently reconciled | CORE-002 | 5 | pending | none audited | secondary feed |
| CORE-004 | Core | News/PIT | Published/available/retrieved times and rights retained per item | Licensed news feed | 4 | pending | none audited | rights/PIT |
| CORE-005 | Core | Canonical research | Idempotent Radar→Journal→ATHENA persisted with replay audit | CORE-001..004 | 5 | pending | none audited | authentic E2E |
| CORE-006 | Core | Risk/valuation | Reproducible scenarios with source-bound uncertainty | CORE-005 | 4 | pending | none audited | authentic evidence |
| CORE-007 | Core | Opportunity/Exit Radar | Price-volume explanations and invalidation with no orders | CORE-002..006 | 4 | pending | none audited | OOS validation |
| CORE-008 | Core | OOS learning | Precommitted predictions and walk-forward outcomes | CORE-005..007 | 5 | pending | none audited | longitudinal observations |
| CORE-009 | Core | Factors/expectations | Factors, reverse valuation and expectations-gap explainable | CORE-006 | 3 | pending | none audited | audited inputs |
| CORE-010 | Core | Catalysts/contradictions | Catalysts, thesis invalidation and devil's advocate PIT-bound | CORE-005 | 3 | pending | none audited | evidence audit |
| CORE-011 | Core | Portfolio analytics | Concentration, attribution and reconciliation read-only | CORE-003 | 3 | pending | none audited | cross-surface E2E |
| CORE-012 | Core | Ollama optional | qwen3:1.7b JSON explanations fail closed without source invention | CORE-005 | 3 | pending | none audited | authorized real run |
| PRODUCT-001 | Product | Dashboard | Verified dates, errors and staleness displayed | CORE-002..006 | 4 | pending | none audited | real E2E |
| PRODUCT-002 | Product | Market | Company selection and legal quotes shown | CORE-001..003 | 5 | pending | none audited | rights |
| PRODUCT-003 | Product | News | Issuer-linked news with provenance and error states | CORE-004 | 4 | pending | none audited | identity/PIT |
| PRODUCT-004 | Product | ATHENA AI | Canonical research and optional explanation presented | CORE-005..012 | 5 | pending | none audited | real E2E |
| PRODUCT-005 | Product | Investors | Source-bound investor context, no authority escalation | CORE-005 | 3 | pending | none audited | cross-surface E2E |
| PRODUCT-006 | Product | Profile/auth | Session, recovery, encryption and privacy verified | Security infrastructure | 4 | pending | none audited | deployed recovery |
| PRODUCT-007 | Product | Portfolio | Owner isolation, event history and paper-only behavior | PRODUCT-006 | 4 | pending | none audited | real acceptance |
| PRODUCT-008 | Product | Navigation/accessibility | Keyboard/screen-reader and route E2E | PRODUCT-001..007 | 3 | pending | none audited | UX acceptance |
| PRODUCT-009 | Product | CI/release | Push SHA checks, release gate, branch protection | GitHub Actions | 5 | pending | none audited | exact-SHA push verification |
| PRODUCT-010 | Product | Recovery/security | Secret custody, encrypted backups, restore and alerts | PRODUCT-009 | 5 | pending | none audited | authorized deployment |
| PRODUCT-011 | Product | Windows local | Low-resource supervised read-only mode and restart recovery | PRODUCT-010 | 3 | pending | none audited | measured hardware |
| PRODUCT-012 | Product | Portable VPS | Private hardened deployment and cost validation | PRODUCT-010 | 2 | pending | none audited | deployment authorization |
| PRODUCT-013 | Product | Broker future | Broker-neutral IBKR paper adapter, reconciliation, kill switch | OOS, legal review | 3 | pending | none audited | future scope, no orders |
| PRODUCT-014 | Product | Broker future activation | Separate explicit human authorization and legal/safety gates | PRODUCT-013 | 5 | pending | none audited | prohibited currently |

Weights: 5 = safety-critical or essential end-to-end gate; 4 = primary user-facing capability; 3 = required supporting capability; 2 = optional deployment alternative. These are provisional and subject to full-scope review. Each ID belongs to exactly one area; cross-area dependencies do not duplicate weight.

**Calculation after complete coverage only:** for each area, `100 × sum(weight × level) / sum(weight)`, where levels are 0 for pending/blocked, 0.25 for implemented+CI, 0.75 for integrated-real-data and 1 for validated-authorized-deployment. A level may be assigned only with SHA-linked reproducible evidence and required gates. A score of 100 additionally requires every applicable criterion at level 1, no critical blocker, all mandatory release checks, and independent scope audit. Until then: **percentage currently not certifiable**. Do not interpret the table's all-pending state as a measured zero.

**Audit coverage:** incomplete; the full module and future-phase inventory must be reconciled against both source documents before certification. Priority is to close the first authentic Market→News→ATHENA journey, not to inflate a score.

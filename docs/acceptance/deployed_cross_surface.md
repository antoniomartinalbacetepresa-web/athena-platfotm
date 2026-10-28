# Deployed cross-surface acceptance — operational gate

The deployed API job is an **opt-in part of the existing** `Validate ATHENA TYCHE` push/PR workflow, not a separate manual workflow. It is skipped by default. When enabled, it is mandatory for the push release-validation gate on `dev/real-market-backend`; pull-request checks remain independent of a deployment.
It checks **a deployed backend**, not a deployed Flutter browser application.
Never count mocked test fixtures or a green standard CI run as operational proof.

## Administrator prerequisites

1. Deploy the **exact** dev/real-market-backend commit to a controlled HTTPS staging environment with canonical Market, News, Investors and ATHENA synthesis data available from the same research cycle. Record deployed SHA independently; this script cannot prove which SHA the server is running.
2. Configure a GitHub environment named `staging-acceptance` with restricted reviewers and the secrets `ATHENA_ACCEPTANCE_BASE_URL`, `ATHENA_ACCEPTANCE_A_EMAIL`, `ATHENA_ACCEPTANCE_A_PASSWORD`, `ATHENA_ACCEPTANCE_B_EMAIL`, `ATHENA_ACCEPTANCE_B_PASSWORD`. Use only disposable authorized staging accounts. Never enter secrets in workflow inputs, repository files or chat.
3. Pre-seed distinct owner A/B portfolios and distinct base currencies. Set environment **variables** `ATHENA_ACCEPTANCE_A_POSITION_ID`, `ATHENA_ACCEPTANCE_B_POSITION_ID`, `ATHENA_ACCEPTANCE_A_CURRENCY`, `ATHENA_ACCEPTANCE_B_CURRENCY`. The IDs must identify separate existing positions. Do not use production customers or create positions during the probe.
4. Independently attest the deployed backend's actual commit SHA and set environment variable `ATHENA_ACCEPTANCE_DEPLOYED_SHA` to that SHA. This variable is an operator assertion, not cryptographic deployment proof; retain deployment logs/attestation separately. Set repository variable `ATHENA_DEPLOYED_ACCEPTANCE_ENABLED=true` **only when deployment automation keeps staging synchronized with each push**. The next push to `dev/real-market-backend` executes the job and requires the deployed SHA to equal the push SHA. With the variable absent/false, the job is skipped and the ordinary release gate remains green if its other checks pass. Never enable prematurely; it will intentionally fail closed on a stale/missing deployment.

The probe requires: HTTPS, health, a **non-empty persisted Market universe without fallback** (not 365-day coverage), News/Investors/ATHENA canonical cycle and hash bindings, presentation-only/no-trading policies, two independent real authenticated owners, owner-specific encrypted Profile currency and Portfolio position markers, and the **authenticated owner-scoped personalization projection**. The personalization projection must exclude sensitive fields and cannot influence recommendations, weighting, learning or trading. The entire returned position-ID sets must be disjoint, not merely the two seeded marker IDs. After A logout, all four protected API routes (me, preferences, personalization, portfolio) must reject A while B's account and personalization remain accessible. It only writes to the session-revocation store via logout; it does not edit Profile, Portfolio, recommendations or orders. Issued tokens are best-effort revoked on exit. It logs no account identity, token, password, position details or profile values.

**Fail closed:** missing deployment, secrets, pre-seeded accounts, canonical synthesis, consistent cycle, markers or revocation returns nonzero. This opt-in job is not currently active because the required deployment/environment evidence is unavailable. A passing result is **deployed API contract evidence only**, not Flutter Web E2E, UI accessibility, full selective-refresh/stale-response behavior, real 365-day history, OOS proof, SMTP delivery, backup/restore or release authorization. Those remain separate acceptance criteria. The administrator must configure branch protection and required checks independently.


## Deployed Flutter Web guest research browser — separate opt-in gate

The deployed API probe above is **not** a Flutter browser E2E. The optional
`Deployed Flutter Web guest research browser (opt-in)` push job runs real
headless Chromium against the **deployed Web origin**, not widget-test Chrome.
It checks Dashboard → Market → News → Investors → ATHENA AI in wide layout,
live canonical HTTP responses, visible verified provenance, **real News
synthesis-only refresh without reloading the independent news feed, and
full News refresh requiring both endpoints**; browser-injected
HTTP 503 fail-closed removal and recovery, and compact Dashboard → Market
navigation. The HTTP 503 is a controlled browser fault, **not** evidence
that a live provider failed. No personal account or position is modified.

Deploy the exact `dev/real-market-backend` Flutter Web build to HTTPS,
compiled with an accessible HTTPS `ATHENA_BACKEND_URL` via
`--dart-define`. Seed verified canonical News/ATHENA synthesis and real
SEC 13F CIK evidence in staging. Set `ATHENA_ACCEPTANCE_WEB_URL` as an
environment **secret** and `ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA` as an
environment **variable** in `staging-acceptance`. The SHA variable is
only an operator assertion; retain independent deployment attestation.
The push CI release artifact now includes `athena-build.json` stamped with
the exact `GITHUB_SHA` after `flutter build web --release`. Deploy the
complete **push** release artifact without replacing this marker. Before
opening the app, the browser probe fetches the deployed marker over HTTPS
from the **same web origin**, bypasses ordinary caches, and rejects missing,
redirected, malformed or mismatched SHA evidence. This closes the previous
gap where the operator-provided SHA variable alone could agree with CI while
the served web bundle belonged to another commit. The marker is still
self-reported by the deployed artifact, not a signed attestation or proof
that the backend runs the same SHA; retain independent deployment logs and
artifact provenance.

Set repository variable `ATHENA_DEPLOYED_BROWSER_ACCEPTANCE_ENABLED=true`
**only after** continuous deployment keeps the web build synchronized
with every push. When enabled, the push release gate requires this job
to succeed; PR checks remain independent. Without configuration, the
browser job is skipped and must not be counted as passed.

Even a passing guest browser job does **not** close two-owner Flutter
session isolation, stale-response ordering, Dashboard-wide selective refresh or stale-response ordering, a full
accessibility audit, 365-day operational history, OOS, SMTP, backups,
or production release authorization. Never upload screenshots or secrets.

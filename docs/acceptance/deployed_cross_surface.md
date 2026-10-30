# Deployed cross-surface acceptance — operational gate

The deployed API job is an **opt-in part of the existing** `Validate ATHENA TYCHE` push/PR workflow, not a separate manual workflow. It is skipped by default. When enabled, it is mandatory for the push release-validation gate on `dev/real-market-backend`; pull-request checks remain independent of a deployment.
It checks **a deployed backend**, not a deployed Flutter browser application.
Never count mocked test fixtures or a green standard CI run as operational proof.

## Administrator prerequisites

1. Deploy the **exact** dev/real-market-backend commit to a controlled HTTPS staging environment with canonical Market, News, Investors and ATHENA synthesis data available from the same research cycle. Record deployed SHA independently; this script cannot prove which SHA the server is running.
2. Configure a GitHub environment named `staging-acceptance` with restricted reviewers and the secrets `ATHENA_ACCEPTANCE_BASE_URL`, `ATHENA_ACCEPTANCE_A_EMAIL`, `ATHENA_ACCEPTANCE_A_PASSWORD`, `ATHENA_ACCEPTANCE_B_EMAIL`, `ATHENA_ACCEPTANCE_B_PASSWORD`. Use only disposable authorized staging accounts. Never enter secrets in workflow inputs, repository files or chat.
3. Pre-seed distinct owner A/B portfolios and distinct base currencies. Set environment **variables** `ATHENA_ACCEPTANCE_A_POSITION_ID`, `ATHENA_ACCEPTANCE_B_POSITION_ID`, `ATHENA_ACCEPTANCE_A_CURRENCY`, `ATHENA_ACCEPTANCE_B_CURRENCY`. The IDs must identify separate existing positions. Do not use production customers or create positions during the probe.
4. Independently attest the deployed backend's actual commit SHA and set environment variable `ATHENA_ACCEPTANCE_DEPLOYED_SHA` to that SHA. The backend deployment must also inject `ATHENA_DEPLOYED_SOURCE_SHA` from the exact source artifact at deployment time; `/api/v1/build` must return the schema `athena.backend-build.v1` and its 40-character lowercase `sourceSha` with `Cache-Control: no-store`. The opt-in API probe compares this runtime marker with `GITHUB_SHA` before authenticating either test owner. Both the environment assertion and the runtime marker are deployment assertions, not cryptographic proof; retain signed deployment provenance separately. Set repository variable `ATHENA_DEPLOYED_ACCEPTANCE_ENABLED=true` **only when deployment automation keeps staging synchronized with each push**. The next push to `dev/real-market-backend` executes the job and requires the deployed SHA to equal the push SHA. With the variable absent/false, the job is skipped and the ordinary release gate remains green if its other checks pass. Never enable prematurely; it will intentionally fail closed on a stale/missing deployment.

The probe requires: HTTPS, health, exact deployed backend runtime SHA marker, a **non-empty persisted Market universe without fallback** (not 365-day coverage), News/Investors/ATHENA canonical cycle and hash bindings (non-empty lowercase 64-character hex for all cycle, PIT and artifact hashes; matching null values never count), presentation-only/no-trading policies, two independent real authenticated owners, owner-specific encrypted Profile currency and Portfolio position markers, and the **authenticated owner-scoped personalization projection**. The personalization projection must exclude sensitive fields and cannot influence recommendations, weighting, learning or trading. The entire returned position-ID sets must be disjoint, not merely the two seeded marker IDs. After A logout, all four protected API routes (me, preferences, personalization, portfolio) must reject A. The probe re-reads all four B surfaces and requires B's original identity, currency, personalization policy and complete position-ID set to remain intact; a still-valid B token returning A's data fails acceptance. It only writes to the session-revocation store via logout; it does not edit Profile, Portfolio, recommendations or orders. Issued tokens are best-effort revoked on exit. It logs no account identity, token, password, position details or profile values.

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

Before guest navigation, the browser gate now requires **both** the deployed Flutter Web build manifest and the staging backend `/api/v1/build` runtime marker to match the exact push SHA. A missing or stale backend marker fails before browser acceptance. This is stronger cross-origin consistency checking, not signed deployment attestation. Configure the backend marker through trusted deployment automation, not through chat or a public runtime input.

Canonical synthesis and News-refresh HTTP evidence must originate from the
**configured HTTPS staging backend origin** (host and effective port) and the
exact API path. A same-path response from another host, an HTTP downgrade,
or a cross-origin request during selective News refresh fails acceptance.
The controlled 503 fault is routed only to that configured backend; recovery
must include a fresh successful response from that backend, not just a
reappearing UI label. These checks do not replace independent provider
provenance verification or the opt-in two-owner API acceptance.

Deploy the exact `dev/real-market-backend` Flutter Web build to HTTPS.
**Before the push build**, set repository variable
`ATHENA_WEB_BACKEND_ORIGIN` to the public HTTPS API origin (no path, query,
credentials or fragment). CI validates it and compiles the release artifact
with `--dart-define=ATHENA_BACKEND_URL=<origin>`. The Flutter default is
`http://127.0.0.1:8000`; a bundle built without the variable is **not
staging-ready**, even when its SHA marker matches. When browser acceptance
is enabled, CI fails closed if the backend origin variable is missing or
invalid. Do not rebuild the published artifact outside CI. Seed verified canonical News/ATHENA synthesis and real
SEC 13F CIK evidence in staging. Set `ATHENA_ACCEPTANCE_WEB_URL` as an
environment **secret** and `ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA` as an
environment **variable** in `staging-acceptance`. The SHA variable is
only an operator assertion; retain independent deployment attestation.
The push CI release artifact now includes `athena-build.json` stamped with
the exact `GITHUB_SHA` after `flutter build web --release`. Deploy the
complete **push** release artifact without replacing this marker. Before
opening the app, the browser probe fetches the deployed marker over HTTPS
from the **same web origin**, bypasses ordinary caches, and rejects missing,
redirected, malformed or mismatched SHA evidence. The v2 manifest also
binds the compiled backend origin to the independently configured
`ATHENA_ACCEPTANCE_BASE_URL` staging secret; a matching SHA with a
localhost or different backend binding is not accepted. This closes the previous
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


## Delayed canonical responses in deployed Chromium

The opt-in deployed Flutter guest journey also captures a **real, live**
canonical ATHENA synthesis response from the configured HTTPS staging backend,
then holds a browser refresh request while a second refresh receives a
**browser-injected** 503. The newer error must remove provenance; releasing the
older, genuine 200 response must not restore it. Only a subsequent successful
live retry may restore the verified synthesis. This checks actual Flutter
request-generation ordering in deployed Chromium, not a mocked widget test,
and does not change or fault the backend.

The runner reports `staleResponseOrderingVerified=true` and
`selectiveRefreshVerified=true` **only after** the deployed journey has
completed successfully. These flags describe the scoped ATHENA synthesis
ordering and News selective/full refresh; they do not establish all-surface
stale ordering, two-owner browser isolation, a complete accessibility audit,
or production readiness. Without a deployed staging run these remain
**unverified**, regardless of green backend/Flutter CI.

The deployment administrator must supply the authorized HTTPS web/API
origins, the exact web build SHA, and seeded canonical synthesis through
protected staging configuration. Never share secrets through chat or commit
them to the repository. A green standard CI with the opt-in job skipped is
not deployed E2E evidence.

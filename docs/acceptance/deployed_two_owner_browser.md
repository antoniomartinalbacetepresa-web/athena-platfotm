# Deployed Flutter Web two-owner acceptance (opt-in)

This is an additional **real Chromium** staging acceptance, not a replacement for
the existing 97 Chrome widget checks, the deployed guest research journey, or
the independent deployed two-owner API gate.

## Preconditions

Deploy the exact `dev/real-market-backend` **push** release bundle and backend
at the same SHA. Configure `ATHENA_WEB_BACKEND_ORIGIN` before building. The
browser gate independently reads `athena-build.json` and `/api/v1/build` and
requires both to match `GITHUB_SHA`, including the web bundle's backend origin.
The markers are not signed deployment attestations.

Configure a protected `staging-acceptance` environment with:

- Secrets: `ATHENA_ACCEPTANCE_WEB_URL`, `ATHENA_ACCEPTANCE_BASE_URL`,
  `ATHENA_ACCEPTANCE_A_EMAIL`, `ATHENA_ACCEPTANCE_A_PASSWORD`,
  `ATHENA_ACCEPTANCE_B_EMAIL`, `ATHENA_ACCEPTANCE_B_PASSWORD`.
- Variables: `ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA`,
  `ATHENA_ACCEPTANCE_A_POSITION_ID`, `ATHENA_ACCEPTANCE_A_CURRENCY`,
  `ATHENA_ACCEPTANCE_B_POSITION_ID`, `ATHENA_ACCEPTANCE_B_CURRENCY`.
- Repository variables: enable the existing guest gate with
  `ATHENA_DEPLOYED_BROWSER_ACCEPTANCE_ENABLED=true` **first**; enable
  `ATHENA_DEPLOYED_OWNER_BROWSER_ACCEPTANCE_ENABLED=true` only when the
  two seeded accounts and synchronized deployment are ready. The owner
  browser gate additionally requires the independent deployed API gate:
  set `ATHENA_DEPLOYED_ACCEPTANCE_ENABLED=true` and confirm both the API
  and guest browser jobs succeed on the **same push SHA**. Missing or
  malformed opt-in flags, or an enabled-but-skipped job, fail the release
  gate. A green PR gate is not deployed evidence.

Both accounts must be authorized, disposable, have disjoint seeded positions,
configured encrypted preferences/personalization, and remain stable during the
probe. Never paste credentials into issues, logs, artifacts or chat. Do not
run against personal customer accounts.

## Evidence required

The browser job opens **two separate Chromium contexts** and authenticates
both through the actual Flutter login UI. It visits Profile and Portfolio,
checks identity and owner-specific state, reloads preferences, refreshes
holdings plus Profile currency through live HTTPS APIs, and verifies private
state via a read-only independent API snapshot using the **browser-issued**
bearer tokens. It logs out A through the UI, confirms revocation on all
protected endpoints and the guest Profile boundary, then checks that B can
still refresh and that B's entire private state is unchanged. It logs out B
through the UI and checks B's revocation. All issued tokens are revoked
best-effort on failure, and browser contexts are closed.

Only safe booleans are emitted. No screenshots, traces, tokens, identities,
position data, URLs or private digests are published. Failures are generic
because browser/HTTP exceptions can contain secrets. A passing test does not
prove real SMTP delivery, external backup restoration, 365-day history,
longitudinal OOS performance, complete accessibility or production readiness.
The guest journey remains responsible for research navigation, selective
News refresh, browser-injected errors, stale response ordering and provenance.

When disabled, the owner step is **skipped** and must never be reported as
passed. Record the exact push SHA, both CI run IDs, and the staging operator's
independent deployment evidence before closing either acceptance criterion.

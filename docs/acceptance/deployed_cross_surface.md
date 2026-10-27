# Deployed cross-surface acceptance — operational gate

This manual workflow is separate from the mandatory push/PR unit/Chrome gate.
It checks **a deployed backend**, not a deployed Flutter browser application.
Never count mocked test fixtures or a green standard CI run as operational proof.

## Administrator prerequisites

1. Deploy the **exact** dev/real-market-backend commit to a controlled HTTPS staging environment with canonical Market, News, Investors and ATHENA synthesis data available from the same research cycle. Record deployed SHA independently; this script cannot prove which SHA the server is running.
2. Configure a GitHub environment named `staging-acceptance` with restricted reviewers and the secrets `ATHENA_ACCEPTANCE_BASE_URL`, `ATHENA_ACCEPTANCE_A_EMAIL`, `ATHENA_ACCEPTANCE_A_PASSWORD`, `ATHENA_ACCEPTANCE_B_EMAIL`, `ATHENA_ACCEPTANCE_B_PASSWORD`. Use only disposable authorized staging accounts. Never enter secrets in workflow inputs, repository files or chat.
3. Pre-seed distinct owner A/B portfolios and distinct base currencies. Set environment **variables** `ATHENA_ACCEPTANCE_A_POSITION_ID`, `ATHENA_ACCEPTANCE_B_POSITION_ID`, `ATHENA_ACCEPTANCE_A_CURRENCY`, `ATHENA_ACCEPTANCE_B_CURRENCY`. The IDs must identify separate existing positions. Do not use production customers or create positions during the probe.
4. Manually dispatch `Deployed ATHENA API acceptance (manual)` **on dev/real-market-backend only**. Capture the workflow run URL, exact checked-out SHA and independent deployed SHA. No automatic production release is triggered.

The probe requires: HTTPS, health, persisted Market universe status, News/Investors/ATHENA canonical cycle and hash bindings, presentation-only/no-trading policies, two independent real authenticated owners, owner-specific encrypted Profile currency and Portfolio position markers, rejection of the revoked A token on all three protected APIs, and survival of owner B session. It only writes to the session-revocation store via logout; it does not edit Profile, Portfolio, recommendations or orders. Issued tokens are best-effort revoked on exit. It logs no account identity, token, password, position details or profile values.

**Fail closed:** missing deployment, secrets, pre-seeded accounts, canonical synthesis, consistent cycle, markers or revocation returns nonzero. This workflow is not yet a mandatory release gate because the required deployment/environment evidence is unavailable. A passing result is **deployed API contract evidence only**, not Flutter Web E2E, UI accessibility, full selective-refresh/stale-response behavior, real 365-day history, OOS proof, SMTP delivery, backup/restore or release authorization. Those remain separate acceptance criteria. The administrator must configure branch protection and required checks independently.

# Browser cross-surface acceptance — Flutter Web (Chrome)

The `Validate ATHENA TYCHE` workflow runs the same production widgets and
controllers through Flutter's Chrome test platform, **in addition** to the
default Flutter test runner. This is a mandatory part of the
`flutter-validation` job, so `Release validation gate` cannot succeed
when this browser lane fails.

The browser suite covers Dashboard / ATHENA synthesis, Market, News,
SEC 13F Investors, the Dashboard–Portfolio boundary, Profile and protected
Personalization. It exercises navigation, selective refresh, stale-response
isolation, provider failure, recovery and accessibility semantics using
controlled HTTP providers. The Profile lane additionally checks guest and
revoked-session boundaries, account-closure behavior, unsaved preference
reloads, protected personalization policy and owner-session isolation.
The test log is uploaded as `flutter-chrome-acceptance.log`.

## Evidence boundary

This gate is a real Chrome rendering/test-engine check, **not** a deployed
application E2E or proof of live providers. It does not close the production
acceptance criteria for AuthSession, Profile, Personalization, Market,
News, Investors or ATHENA AI. In particular, it cannot prove an operational
database snapshot, >=365-day eligible-universe history coverage, independent
corporate-action reconciliation, longitudinal OOS forecasts, real SMTP
delivery, off-site backups, key custody or production deployment.

For full acceptance, run an authorized deployed E2E against a controlled
operational environment, record the exact release SHA, browser, timestamp,
owner isolation, provider evidence and failures, and verify the remaining
operational gates independently. Fixtures must never be presented as
production evidence. No recommendation weighting, learning promotion or
automatic trading is authorized by this browser gate.

## Browser gate scope (non-production)

The Chrome lane includes `profile_page_test.dart` and
`profile_personalization_shell_test.dart` alongside the Dashboard, Market,
News, Investors and Dashboard–Portfolio tests. A failing Profile or
Personalization browser test fails the Flutter validation job and therefore
the release validation gate. These are widget-level browser tests with
controlled transport and memory token stores; they do **not** demonstrate
real secure-storage persistence, real SMTP recovery, a deployed session,
production owner isolation or a complete cross-route E2E.

The next acceptance step is a deployed, authorized AuthSession–Profile–
Portfolio–Dashboard journey using two real test accounts and an explicit
logout/revocation boundary, with independently captured request/response
contracts, accessibility findings and exact build SHA. Do not capture
credentials, access tokens, capital or personal data in CI artifacts.

## AuthSession–Profile–Portfolio browser acceptance

The mandatory Chrome lane also executes these existing integration tests:

- `profile_session_transition_e2e_test.dart`: a mounted Profile rejects
  obsolete `/auth/me` responses when the authenticated owner or authority
  generation changes, including same-token replacement.
- `profile_portfolio_logout_cross_surface_e2e_test.dart`: confirmed Profile
  logout removes Portfolio capabilities across real Flutter routes; a later
  owner starts with fresh authority.

These tests use controlled HTTP responses and mocked credential storage;
they are not evidence that the deployed browser's secure storage, real
accounts, backend revocation, or owner-scoped database have been verified.
The release gate must remain red if any of these Chrome tests fail. A
deployed two-account lifecycle and an independent API/database isolation
check are still required before marking owner isolation production-accepted.

### Portfolio Chrome gap discovered 2026-10-27

The complete `authenticated_portfolio_page_e2e_test.dart` remains mandatory
in the default Flutter test lane, where all its tests passed. Adding that
entire file to Chrome produced **three Chrome-only failures** (coordinated
refresh, owner change during add-position dialog, and owner change during
remove confirmation), while 94 other Chrome tests passed. The exact failure
mechanism is not established by the CI log. Do not claim Chrome acceptance
for those three cases or weaken their assertions merely to turn CI green.
The whole file is withheld from the Chrome lane pending diagnosis with
expanded failure reporting and a browser-specific reproduction; no test
or product functionality was deleted. Profile session transitions and the
Profile-to-Portfolio logout lifecycle remain required in Chrome.

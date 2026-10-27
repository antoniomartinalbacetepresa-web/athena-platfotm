# Browser cross-surface acceptance — Flutter Web (Chrome)

The `Validate ATHENA TYCHE` workflow runs the same production widgets and
controllers through Flutter's Chrome test platform, **in addition** to the
default Flutter test runner. This is a mandatory part of the
`flutter-validation` job, so `Release validation gate` cannot succeed
when this browser lane fails.

The browser suite covers Dashboard / ATHENA synthesis, Market, News,
SEC 13F Investors and the Dashboard–Portfolio boundary. It exercises
navigation, selective refresh, stale-response isolation, provider failure,
recovery and accessibility semantics using controlled HTTP providers.
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

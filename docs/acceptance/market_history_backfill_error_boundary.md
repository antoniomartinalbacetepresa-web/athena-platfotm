# Backfill failure-report confidentiality boundary

Market-history backfill results can be returned to API clients or printed by the operational CLI. A provider or SQLite exception may include a credential, request URL, private filesystem path, or server-supplied content. The backfill now records **fixed stage-specific failure messages**, never raw exception strings, while retaining the selected public instrument symbol, failed count, progress status and successful per-instrument continuation. Validation failures remain fail-closed and cannot persist an invalid provider response.

Stages distinguish instrument identity, provider I/O, provenance (including declared symbol), PIT observation window, and persistence. The stage is diagnostic only: it does not attest the provider, establish historical depth, prove the origin of the SQLite database, or authorize any market action. Detailed provider diagnostics belong in a separately protected observability system with explicit redaction and access controls; they must not be inserted into user-facing failure reports.

Regression coverage injects credential-bearing provider errors (including ValueError), untrusted provider fields and persistence errors, and verifies that neither the report nor its API serialization reveals those values. No production credentials or database snapshot are used.

The same confidentiality boundary applies to secondary corporate-action backfills, including the targeted verified reconciliation workflow. Both return a fixed `secondary_provider_or_ingestion_failed` code rather than arbitrary Alpha Vantage exception strings; corporate-action ingestion itself no longer interpolates untrusted provider labels into provenance exceptions. Existing event-conflict and incomplete-status rules remain unchanged. This does not prove that an independent source has been deployed or that any production event has been reconciled.

## Same-day PIT observation boundary

The requested `to_date` is a **calendar-day limit**, not proof that every
intraday instant on that date was already observable. After each provider
response, the service captures its UTC completion instant and rejects the
**entire instrument response** if either timestamp alias identifies an instant
later than that completion time, even when its date equals `to_date`.
No partial observations are persisted from a rejected response. Legitimate
observations received after a slow request remain eligible when their event
instant is no later than the response completion instant. The failure remains
a fixed stage-specific message and does not expose provider payloads.

This is an ingestion no-lookahead boundary, not independent attestation of the
provider's historical truth or proof of operational 365-day coverage.

## Provider authorization before network I/O

The market-history backfill service now applies the repository's forbidden-source
policy to `source_provider` **before** initializing SQLite, selecting instruments,
or calling the history adapter. Plain, separator-obfuscated, URL-encoded and
HTML-entity-encoded FMP labels are rejected without a provider request.
Write-time rejection remains in place as a second line of defense.

This prevents an operator from accidentally contacting a forbidden FMP source
through a custom adapter. It does **not** independently prove that a third-party
adapter is honest about its declared provider identity or that a free provider's
license permits a particular production use. Operational source authorization,
PIT evidence and 365-day coverage remain separate requirements.

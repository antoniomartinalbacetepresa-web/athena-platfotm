# PIT price selection for retrospective recommendation evaluation

The outcome evaluator and frozen-benchmark evaluator now share a single
read-only selector of persisted market observations. The old SQL compared
ISO-8601 timestamps lexicographically, which is incorrect when source records
carry different UTC offsets. It could select a later-retrieved revision after
the evaluation cutoff, or choose the wrong revision of an identical instant.

The shared selector uses SQLite date conversion only as a broad prefilter and
then checks each original timezone-aware timestamp at Python microsecond
precision. It requires the observation to lie in the requested interval and
the retrieval instant to be between the observation and the evaluation PIT
cutoff. Malformed/naive timestamps and non-positive/non-finite prices are
excluded. The selector also rejects a non-null source timestamp that is
malformed, timezone-naive or later than the retrieval instant, and applies
the same FMP/empty-provider exclusion as the market observation repository.
This applies to imported legacy rows as well as current ingestion. Equal UTC observation instants are deduplicated by the latest
eligible retrieval instant, then the persisted row ID. Raw close remains
preferred over adjusted close when present.

This policy applies consistently to entry price, exit price, peak-to-trough
drawdown and the explicitly frozen benchmark. No observation is rewritten,
no backfill is triggered and no model is promoted. Tests use synthetic
records with offset collisions and a future retrieval disguised by its
textual timezone representation. They are regressions only, **not**
operational OOS evidence or an attestation of independent market sources.

Operational closure still requires real precommitted forecasts, expired
horizons, a consistent authorized database snapshot, verified outcome and
benchmark provenance, FX/corporate-action adjustments, sufficient samples,
and independent validation. Until then, no trading, weighting, production
learning or predictive-skill claim is authorized.

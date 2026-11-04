# Independent offline verification of paired PIT diagnostic evidence

After an authorized operator runs `export_operational_history_bundle`, preserve the **printed bundle SHA-256 in a separately controlled audit record**. Transfer the ZIP to a separate verification host and run from the backend directory:

```bash
PYTHONPATH=. python -m scripts.verify_operational_history_bundle \
  --bundle /secure/evidence/athena-history-actions-20261029.zip \
  --expected-sha256 <SHA256_FROM_SEPARATE_CUSTODY_RECORD>
```

The command requires an independently supplied, lowercase 64-character SHA-256. It verifies the ZIP against that digest **before** interpreting any contained metadata. It then checks the exact three-member archive, each child report's SHA-256, complete JSONL record counts, order and identities, PIT cutoff, eligible-universe arithmetic, unresolved dividend/split categories, and explicit `false` authority flags. An archive with rehashed but incomplete or reclassified rows fails. The verifier is read-only, uses no provider/network calls and does not extract ZIP files to disk. It returns exit code `0` for an internally consistent diagnostic artifact and `3` for invalid or unverifiable evidence. Failures print no source path or sensitive row data.

**Scope boundary:** a valid digest is not an authenticity signature. The verifier cannot prove that the separately retained digest came from a trusted operator, that the input database was operational, that the eligible universe is complete, that the providers are independent, or that a historical PIT claim is genuine. It cannot authorize production, learning, weighting or trading. A green result must be accompanied by a separately audited source snapshot, custody records, acquisition provenance, real 365-day eligible-universe measurement, and independent corporate-action reconciliation. Never publish instrument-level operational exports or database files in GitHub Actions artifacts or source control.

This verifier is deliberately independent of the exporters' runtime and databases, allowing an operator to detect transfer corruption and internal contradictions on an isolated audit host. It is **not** a substitute for executing the full acceptance on an authorized operational snapshot.

**Child-snapshot consistency:** the exporter refuses to publish if the two
independently generated child reports have different SQLite snapshot SHA-256
values. The offline verifier enforces the same equality even if the child
reports and custody digest have been recalculated. The frozen source-generation
SHA-256 is recorded separately: SQLite online backup can rewrite file-header
counters, so its byte hash need not equal either child snapshot hash. These
checks establish internal consistency, **not** independent proof that the
children originated from the claimed source generation or from production.


## Fail-closed diagnostic blocker gate (optional)

On the isolated verification host, use the same independently retained custody
digest and add `--require-zero-blockers` to the command above. Exit code `4`
means that the verified diagnostic reports **an empty eligible universe**, one
or more instruments without current 365-day coverage, or one or more unresolved
dividend/split reconciliation events. The machine-readable output includes
`diagnosticBlockersZero` and `diagnosticBlockingReasons` without exposing
individual instruments. Exit code `3` still means the bundle failed integrity
verification; exit code `0` in strict mode means only that the internally
consistent diagnostic has a **nonempty** eligible universe and zero reported
blockers. Without the flag, valid bundles with gaps still exit `0` for
inspection and export of the complete worklist.

This is deliberately **not** a production-readiness, provenance, external
timestamp or independent-provider-agreement gate. A zero-blocker diagnostic
may come from fixtures or an incomplete operational universe. A real acceptance
requires authorized snapshot custody, independent evidence of the eligible
universe, operational source and PIT acquisition, plus second-family dividend/
split agreement. The output retains `operationalOriginVerified=false`,
`productionCoverageClaimed=false` and `productionAuthorization=false`.
No automatic backfill, weighting, learning promotion or trading is authorized.

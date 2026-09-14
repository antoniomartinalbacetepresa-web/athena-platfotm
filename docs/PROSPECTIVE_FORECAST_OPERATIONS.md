# Manual prospective research generation

Run from `backend` with the existing `ATHENA_DATABASE_PATH` configuration:

```sh
PYTHONPATH=. python scripts/generate_research_forecast.py \
  --template /path/to/research-v3-template.json \
  --model /path/to/reviewed-linear-model.json \
  --artifact-sha256 SHA256_FROM_REVIEWED_ARTIFACT
```

The pin must come from the artifact review, not be silently calculated by this
command. The model must implement `research-linear-total-return-v1`; coefficients,
scaling and feature paths must be explicit. No default or trained artifact ships
with ATHENA. The template must be valid v3 with resolvable persisted PIT inputs,
a new identity and a future forecast availability deadline/period. The template's
expectedValue is not measured evidence; inference determines the final value.

The executor verifies bytes, inputs and timing, then the existing store atomically
persists the finalized specification and receipt-v2. Output is research-only JSON;
failure exits nonzero without internal diagnostics. A transport/serialization
failure is not proof that no write occurred: inspect the existing records before
retrying. Generation rejects existing identities rather than running them again.
Do not change identity to bypass a failure or selectively discard bad forecasts.

After successful generation, freeze the intended selection before every period
starts with `scripts/prospective_cohort.py register`. This command does not create
a cohort, evaluate outcomes, approve policy, train a model or promote learning.
Real source coverage, artifact calibration, naturally mature prospective cohorts
and governed longitudinal evidence remain operational gates. Synthetic tests do
not satisfy them. Never reinterpret excess-return artifacts as total return.

Each prospective cohort must use one method, horizon and exact model identity
(name, version and artifact SHA-256), as resolved from its observed receipts.
Registration and later reads reject mixed identities even if method labels match.
A model change requires a separate prospectively sealed cohort, not pooling older
forecasts into a new apparent model history. Existing mixed cohorts fail closed;
do not rewrite their immutable selection or label them as comparable evidence.

New selections use `research-prospective-cohort-v2`. Their `modelIdentity` is
included in the cohort hash and compared with observed receipts on every read.
Legacy v1 selections remain readable and idempotent but are not retroactively
upgraded or represented as having an ex-ante model pin. No migration may fabricate
that missing historical commitment. Both versions remain research-only.

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
## Recover a persisted result without inference

If output was lost, locate the final specification hash in the existing records:

```sh
PYTHONPATH=. python scripts/generate_research_forecast.py \
  --recover-specification-hash FINAL_SPECIFICATION_SHA256 \
  --model /path/to/original-model.json \
  --artifact-sha256 ORIGINAL_REVIEWED_ARTIFACT_SHA256
```

Recovery is mutually exclusive with `--template`. It only reads and revalidates
the original specification and observed receipt-v2 and requires the original
model bytes/pin. It never invokes inference or appends forecast/receipt evidence,
including when a record is missing. Missing evidence fails closed. This does not
restore deleted evidence, reconstruct historical predictions or certify skill.


## Medición del denominador precomprometido (sin inferir skill)

Tras registrar una cohorte v2 y cuando sus horizontes venzan, el operador puede
medir la presencia de errores **y outcomes realmente persistidos**, sin aportar
manualmente listas de hashes que aparenten evaluaciones:

```sh
PYTHONPATH=. python scripts/prospective_cohort.py measured \
  --cohort-id COHORT_ID \
  --expected-cohort-hash SEALED_COHORT_SHA256 \
  --as-of 2026-10-29T20:00:00Z
```

El corte es explícito y con zona horaria. La consulta mantiene el denominador
inmutable: distingue previsiones todavía no vencidas, vencidas sin resultado y
vencidas con cadena specification → error → outcome persistida e íntegra. Rechaza
duplicados, inconsistencias de identidad/periodo, resultados anteriores al
vencimiento y referencias a outcomes ausentes. No inserta errores ni outcomes,
no evalúa retrospectivamente predicciones, no altera modelos y no envía órdenes.
Si el almacén de errores todavía no existe, declara cero mediciones.

`persistedOutcomeChainVerified` verifica solamente coherencia del almacenamiento;
**no** demuestra procedencia independiente de datos de mercado, cobertura real
del universo, ausencia de selección de supervivientes, independencia estadística,
calibración, rentabilidad ni skill. Por ello `independentMarketSourceVerified`,
`predictiveSkillEstablished`, `outcomeEvidenceVerified` y todas las
autoridades productivas permanecen en `false`. No usar fixtures para declarar
cumplimiento operativo. Se requiere una instantánea autorizada y consistente
de la base operativa y validación externa de los resultados para cerrar OOS.

## Estadísticas descriptivas de errores persistidos

La operación `measured` también devuelve `maturedMeasurementCoverage`
(fracción de horizontes vencidos con cadena de error y outcome persistida) y
`observedErrorStatistics`: tamaño de muestra, sesgo medio firmado, error
absoluto medio, raíz del error cuadrático medio y máximo error absoluto,
todos expresados en **fracciones de retorno total**. Las métricas se calculan
exclusivamente sobre los errores persistidos que han superado las validaciones
de identidad, PIT y outcome. Si no hay observaciones, las estadísticas son
`null`; si todavía no venció ningún horizonte, la fracción de cobertura es
`null`, no un 100% ficticio.

Estas estadísticas son **descriptivas y potencialmente sesgadas por la falta
de outcomes**: el denominador precomprometido y la lista completa de vencidos
sin medición siguen siendo obligatorios para interpretarlas. No demuestran
calibración, skill, significación estadística, calidad de fuentes externas,
aprobación de ponderaciones ni autoridad de aprendizaje/trading.

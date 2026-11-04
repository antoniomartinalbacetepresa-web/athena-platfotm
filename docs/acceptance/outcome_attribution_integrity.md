# Posterior Performance Attribution — canonical integrity gate

Professional Research Cycle outcome binding re-derives **Performance Attribution**
from its nested PIT inputs before binding to the frozen research cycle.
The append-only outcome repository repeats this validation on **writes and reads**.
The claimed `attributionKey`, `explainedReturn` and `residualReturn`
must match the deterministic canonical service output, including factor values,
FX identity, source references, PIT timestamps and research-only policy.

A caller cannot legitimize forged arithmetic by recalculating the outer
`outcomeHash`. Missing provenance, non-finite or boolean numeric inputs,
mismatched factor metadata and noncanonical projections fail closed.

Acceptance: existing API/persistence regressions remain green; targeted
regressions re-seal a mutated outer hash and prove the repository rejects
forged identity, arithmetic and provenance. Direct outcome binding also
rejects a tampered residual. This is **code-integrity evidence**, not proof
that providers are truthful, that data are operational, that storage is WORM,
that residual return is alpha or that longitudinal OOS is sufficient.
No automatic learning, weighting, scoring promotion or trading is enabled.

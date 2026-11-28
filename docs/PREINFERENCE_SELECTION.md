# Pre-inference selection: intent only

The existing prospective cohort ledger freezes forecasts after inference and
before outcome periods. It does not prove that unsuccessful or inconvenient
inferences were not excluded before registration.

`ResearchInferenceSelectionPlanService.register` stores a bounded canonical list
of valid v3 templates plus the reviewed model artifact SHA-256. Inputs must be
persisted/PIT-resolvable and available before the physical selection seal; that
seal must precede forecast deadlines and period starts. Plan identity, template
content and model pin cannot be replaced. Reads revalidate content and inputs.
This table stores intent, not another forecast/outcome database.

This initial service is not yet mandatory in the generator. It explicitly returns
`executionEnforcementImplemented=false` and `forecastEvidenceProduced=false`.
Do not count a plan as having executed a model, closed selection bias, produced a
forecast or satisfied OOS sufficiency. The next integration must require a plan
before inference, bind every generated identity/model/input to it, retain failed
and missing attempts in its denominator and prevent retrospective replacement.
Legacy cohorts must never be assigned fabricated pre-inference commitments.

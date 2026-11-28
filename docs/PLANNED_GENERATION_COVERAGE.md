# Planned generation coverage

ResearchInferencePlanCoverageService reconciles every immutable planned template with existing persisted specifications and observed receipts. It binds template content (except inference-derived value/availability/hash), model artifact, deadline and execution start after the plan seal. Missing generations remain in selectedCount and missingTemplateHashes. Missing reasons are not inferred: failed execution and never-attempted execution are not claimed distinguishable.

This read-only service does not generate forecasts, verify outcomes or grant production authority. It is not yet mandatory in governed OOS. Next: connect this fixed denominator to that route and add durable attempt accounting; never silently drop missing planned generations. Synthetic regression tests are software evidence only.

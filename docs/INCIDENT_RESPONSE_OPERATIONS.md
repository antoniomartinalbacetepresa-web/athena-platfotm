# ATHENA TYCHE — Incident response operations

This runbook defines the minimum operational incident-response boundary. It is a procedure and acceptance contract; its presence in the repository is not evidence that a production exercise, escalation channel, credential revocation, or recovery has been verified.

## Severity and immediate containment

Treat suspected credential disclosure, unauthorized owner-data access, corrupted financial provenance, or loss of recovery capability as a high-severity incident. Stop affected ingestion or user-facing mutation paths when continuing could amplify damage. Do not enable trading or alter canonical market weighting as an incident workaround.

## Required response sequence

1. Assign a named incident owner in the deployment/operations system.
2. Record detection time, affected deployment, observed symptoms and evidence sources without copying secrets into tickets or logs.
3. Contain the affected component. Revoke compromised sessions/tokens and rotate affected credentials through the deployment secret manager when compromise is plausible.
4. Preserve database and relevant audit evidence before destructive remediation when safe to do so.
5. Validate recovery using the verified backup/restore procedure. A local fixture or CI restore does not count as production recovery evidence.
6. Verify owner-data isolation, authentication, provenance and fail-closed behavior before restoring affected traffic.
7. Record measured detection, containment and recovery timestamps. Use actual measurements rather than inferred RPO/RTO.
8. Complete a post-incident review and update controls/tests where a software gap contributed.

## Operational acceptance

Incident-response readiness requires explicit evidence of all of the following: a runbook review within 90 days, an exercise within 180 days, an assigned incident owner, a verified escalation channel, a verified credential-revocation procedure and a verified recovery procedure. `IncidentResponseReadinessService` evaluates only operator-supplied evidence and never infers these facts from repository tests.

Deployment tooling can evaluate a JSON evidence export with:

```text
python -m scripts.incident_response_readiness --evidence <OPERATOR_EVIDENCE_JSON>
```

The JSON object must provide `runbookReviewedAt`, `exerciseCompletedAt`, `incidentOwnerAssigned`, `escalationChannelVerified`, `credentialRevocationProcedureVerified` and `recoveryProcedureVerified`. Timestamps must be timezone-aware ISO-8601 values (or `null` when evidence is absent); claims must be actual JSON booleans. The command exits successfully only when every gate passes. Its report remains `diagnostic_only`, with `productionAuthorization=false` and `automaticTrading=false` even when ready.

The evidence file is an input from the deployment/incident system. Do not commit a filled production evidence file, credentials, contact details, secret-manager identifiers or tokens to this repository. A locally authored JSON file proves evaluator behavior only; it does not prove a production exercise occurred.

## Exercise scenarios

At minimum exercise: leaked authentication secret/session compromise; unavailable or corrupted primary database requiring restore; incorrect or untrusted market provenance; and loss of the recovery-delivery channel. Exercises must verify containment and recovery without exposing secrets, fabricating production evidence, authorizing automatic weighting changes or enabling automatic trading.

## Evidence handling

Store operational evidence in the deployment/incident system, not as hard-coded booleans or credentials in this repository. Deployment automation may export the six non-secret acceptance facts into a temporary evidence file for the evaluator, but absence of any required fact must remain fail-closed. Delete temporary exports according to the deployment platform's evidence-retention policy; the application repository is not the system of record for operational proof.

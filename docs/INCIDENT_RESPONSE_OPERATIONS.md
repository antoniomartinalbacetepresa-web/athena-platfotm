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

## Exercise scenarios

At minimum exercise: leaked authentication secret/session compromise; unavailable or corrupted primary database requiring restore; incorrect or untrusted market provenance; and loss of the recovery-delivery channel. Exercises must verify containment and recovery without exposing secrets, fabricating production evidence, authorizing automatic weighting changes or enabling automatic trading.

## Evidence handling

Store operational evidence in the deployment/incident system, not as hard-coded booleans or credentials in this repository. Future integration may feed signed or authenticated deployment evidence into readiness diagnostics, but absence of such evidence must remain fail-closed.

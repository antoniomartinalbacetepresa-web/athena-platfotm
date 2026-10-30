# Scheduled verified backup: secondary mount boundary

The Linux systemd timer and service in `deploy/systemd/` are deployment templates, **not evidence that a timer is installed or executing**. The production operator must install and enable them on the authorized host, provide a separately mounted encrypted secondary filesystem, and retain protected journal and restore evidence. Do not send paths containing secrets or credentials in chat.

## Mount-loss failure policy

The scheduled entrypoint verifies that the secondary directory is a mount on a filesystem distinct from both the database and primary backup. It now pins the secondary filesystem device identity for one cycle and passes a fail-closed guard to the integrated backup workflow. That guard is invoked **before secondary copy**, **after the verified secondary copy and isolated restore, before any retention**, and **again before primary retention**. The entrypoint also checks the mount at the end. A missing, substituted or locally fallen-back secondary filesystem stops the cycle before subsequent retention; existing primary recovery points are preserved if the mount is lost during copy/restore.

This is a defense against a mount disappearing between the initial check and the verified copy. It **does not make a filesystem mount check atomic with every write or unlink**, and it cannot prove that the secondary volume is geographically off-site, encrypted in practice or under separate administrative custody. Production operations should additionally bind mount lifecycle to the service, monitor mount health and timer execution, and verify an independent off-site restore. No green CI or local test is accepted as scheduled/off-site/production recovery evidence.

## Operational closure

Require an authorized deployment record identifying the timer unit and exact deployed SHA, a complete successful timer invocation, the source backup SHA-256 and manifest, a verified secondary copy, a separately executed isolated restore, retention results, the mount's operational origin, encrypted custody and independent off-site location attestation. Confirm failures do not delete prior primary recovery points. Until these artifacts are independently reviewed, `scheduledExecutionVerified`, `offsiteLocationVerified` and `productionRecoveryVerified` remain false.

## Retention guard at each destructive operation

The scheduled mount guard is now passed into both secondary and primary
retention. Each managed backup and manifest deletion rechecks the secondary
mount identity **after** full inventory verification, not just before
retention starts. If the secondary mount disappears during verification,
retention fails closed and the older primary recovery point is preserved.
The same check runs during primary pruning because a missing secondary
recovery boundary must never authorize loss of older primary copies.
Failure-injection regressions cover both phases; they do not establish a
real off-site installation or eliminate the small check-to-unlink race.
Production closure still requires evidence of an installed timer, an
independent encrypted mount and a real isolated restore.

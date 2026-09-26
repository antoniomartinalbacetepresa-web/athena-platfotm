# Production recovery operations

This runbook defines the deployment boundary for ATHENA database recovery. It is an operational procedure, not evidence that any production scheduler, off-site store, or restore drill is currently deployed.

## Required deployment flow

1. Schedule `backend/scripts/run_verified_backup_cycle.py` outside the application process. The scheduler must provide the live database path, a dedicated primary backup directory, retention, and a stable prefix.
2. Treat a non-zero exit as a failed backup cycle. The cycle creates the SQLite backup, verifies its manifest and SHA-256, executes an isolated restore drill, and only then applies retention.
3. After a successful primary cycle, copy the generated backup and manifest to a physically or administratively independent destination with `backend/scripts/copy_verified_backup_secondary.py`.
4. Treat the secondary copy as valid only when that command exits successfully. It verifies the primary against its manifest before copying and verifies the copied bytes afterward.
5. The secondary-copy script deliberately reports `offsiteLocationVerified=false`. Deployment tooling or a human operator must establish that the configured destination is genuinely off-site/independent; the application must not infer this from a filesystem path.
6. Feed measured operational evidence into the production-recovery readiness diagnostic: last successful backup, last restore drill, scheduler enabled state, verified off-site state, measured RPO, and measured RTO.
7. Production recovery is not ready unless every readiness check passes. CI fixtures and local test directories are never production evidence.

## Scheduler contract

A production scheduler should invoke the verified cycle at least as frequently as the accepted RPO requires. The current readiness target rejects backup evidence older than 24 hours. The scheduler configuration itself belongs to deployment infrastructure and must be protected/reviewed independently of application code.

Example command shape:

```text
python -m scripts.run_verified_backup_cycle --database <LIVE_DB> --directory <PRIMARY_BACKUP_DIR> --keep-last 7
python -m scripts.copy_verified_backup_secondary --backup <CREATED_BACKUP> --manifest <CREATED_MANIFEST> --destination <INDEPENDENT_DESTINATION>
```

Placeholders above are intentional. Do not commit production paths, credentials, bucket tokens, mount secrets, or encryption keys.

## Failure policy

Do not delete the primary backup merely because the secondary copy fails. Alert on any failed cycle or failed secondary verification. Never overwrite existing backup evidence with the same name. Do not mark `scheduledBackupEnabled`, `offsiteCopyVerified`, RPO, or RTO as satisfied until the deployment/operator has measured those facts.

## Recovery acceptance

A real deployment acceptance requires all of the following: a recent verified backup, a recent restore drill, scheduler evidence, independently verified off-site storage, measured RPO within target, and measured RTO within target. Passing repository tests demonstrates implementation behavior only.

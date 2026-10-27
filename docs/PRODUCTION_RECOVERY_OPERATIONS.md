# Production recovery operations

This runbook defines the deployment boundary for ATHENA database recovery. It is an operational procedure, not evidence that any production scheduler, off-site store, or restore drill is currently deployed.

## Required deployment flow

1. Schedule `backend/scripts/run_verified_backup_cycle.py` outside the application process. Supply the live database path, dedicated primary directory, independent secondary directory, retention and stable prefix. The scheduler itself is not provided or verified by this repository.
2. Use the integrated `--secondary-directory` option: create the primary SQLite backup, verify manifest/SHA-256/integrity, run an isolated primary restore, copy to secondary, verify secondary integrity and run an isolated secondary restore **before primary retention**. Any failed step must produce a nonzero exit and leave older primary recovery points untouched.
3. The standalone `backend/scripts/copy_verified_backup_secondary.py` remains available for copying existing verified backups. Do not use a two-command primary-then-secondary sequence with aggressive retention: the first command can delete an older primary backup before the secondary copy succeeds.
4. Treat the secondary copy as valid only when the integrated or standalone command exits successfully. Neither proves physical off-site independence.
5. The secondary-copy script deliberately reports `offsiteLocationVerified=false`. Deployment tooling or a human operator must establish that the configured destination is genuinely off-site/independent; the application must not infer this from a filesystem path.
6. Feed measured operational evidence into the production-recovery readiness diagnostic: last successful backup, last restore drill, scheduler enabled state, verified off-site state, measured RPO, and measured RTO.
7. Production recovery is not ready unless every readiness check passes. CI fixtures and local test directories are never production evidence.

## Scheduler contract

A production scheduler should invoke the verified cycle at least as frequently as the accepted RPO requires. The current readiness target rejects backup evidence older than 24 hours. The scheduler configuration itself belongs to deployment infrastructure and must be protected/reviewed independently of application code.

Example command shape:

```text
python -m scripts.run_verified_backup_cycle --database <LIVE_DB> --directory <PRIMARY_BACKUP_DIR> --secondary-directory <INDEPENDENT_DESTINATION> --keep-last 7
```

Placeholders above are intentional. Do not commit production paths, credentials, bucket tokens, mount secrets, or encryption keys.

## Failure policy

Do not delete the primary backup merely because the secondary copy fails. The integrated cycle deliberately skips primary retention on secondary-copy or secondary-restore failure; the newly created primary backup may remain for investigation. Alert on any failed cycle or failed secondary verification. Never overwrite existing backup evidence with the same name. Do not mark `scheduledBackupEnabled`, `offsiteCopyVerified`, RPO, or RTO as satisfied until the deployment/operator has measured those facts. The optional `--offsite-attestation` is only an operator declaration and never changes `offsiteLocationVerified=false`.

## Recovery acceptance

A real deployment acceptance requires all of the following: a recent verified backup, a recent restore drill, scheduler evidence, independently verified off-site storage, measured RPO within target, and measured RTO within target. Passing repository tests demonstrates implementation behavior only.

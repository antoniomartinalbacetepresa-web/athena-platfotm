# Production recovery operations

This runbook defines the deployment boundary for ATHENA database recovery. It is an operational procedure, not evidence that any production scheduler, off-site store, or restore drill is currently deployed.

## Required deployment flow

1. Schedule `backend/scripts/run_verified_backup_cycle.py` outside the application process. Supply the live database path, dedicated primary directory, independent secondary directory, retention and stable prefix. The primary and secondary directories must not equal the live database directory; the secondary must not equal, contain or be nested inside the primary directory (including symlink aliases). These path checks prevent obvious unsafe layouts but do **not** establish off-site physical independence. An opt-in Linux systemd scheduler template is included in `deploy/systemd/`, but installation, execution and monitoring are not verified by repository CI.
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

The backup and restore paths now stage each operation in a unique directory on the destination filesystem and publish via exclusive hard links, so a concurrent process cannot be overwritten after the preflight. The destination filesystem must support hard links; otherwise the operation fails closed. An orphaned managed backup without a manifest blocks retention until an operator investigates it. Do not delete the primary backup merely because the secondary copy fails. The integrated cycle deliberately skips primary retention on secondary-copy or secondary-restore failure; the newly created primary backup may remain for investigation. Alert on any failed cycle or failed secondary verification. Never overwrite existing backup evidence with the same name. Do not mark `scheduledBackupEnabled`, `offsiteCopyVerified`, RPO, or RTO as satisfied until the deployment/operator has measured those facts. The optional `--offsite-attestation` is only an operator declaration and never changes `offsiteLocationVerified=false`.

## Recovery acceptance

A real deployment acceptance requires all of the following: a recent verified backup, a recent restore drill, scheduler evidence, independently verified off-site storage, measured RPO within target, and measured RTO within target. Passing repository tests demonstrates implementation behavior only.

## Linux systemd hourly scheduler template (deployment required)

The repository now supplies `deploy/systemd/athena-verified-backup.service` and
`deploy/systemd/athena-verified-backup.timer`. **They are not installed by
committing them.** A deployment administrator must provision an unprivileged
`athena-backup` account with read access to the live database, write access to
the primary backup directory and the independent secondary mount, and a Python
3.12+ virtual environment at `/opt/athena/backend/.venv`. Deploy only the
authorized `dev/real-market-backend` build; never execute against `main`.

Provision `/etc/athena/backup.env` with permissions `0600`, owned by root,
containing **absolute paths**, for example:

```ini
ATHENA_BACKUP_DATABASE=/srv/athena/data/athena.db
ATHENA_BACKUP_PRIMARY_DIRECTORY=/var/lib/athena-backups
ATHENA_BACKUP_SECONDARY_DIRECTORY=/mnt/athena-independent-backups
ATHENA_BACKUP_KEEP_LAST=7
ATHENA_BACKUP_ENCRYPTED_STORAGE_CONFIRMED=true
```

The encryption confirmation is an explicit operator assertion, not cryptographic proof. Do not set it until the independently managed secondary mount has verified encryption at rest and appropriate access controls. These paths are examples, not deployment assertions. Create both backup
directories before enabling the timer. The secondary path must be a mounted,
independent filesystem with a different device identifier from the live database
and primary backup storage. The entry point refuses a missing/unmounted
secondary destination, unsafe retention (<2 or >365), overlapping invocations
(using an exclusive runtime lock), and failed secondary verification/restore.
A separate filesystem **does not prove an off-site location**: operators must
independently verify the storage failure domain, encryption and access policy.
If the mount disappears, the command must fail rather than silently write a
local fallback copy.

After inspecting and adapting the service's account, working directory,
Python executable and hardening restrictions to the authorized deployment,
install the unit and timer in `/etc/systemd/system/`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now athena-verified-backup.timer
sudo systemctl start athena-verified-backup.service
sudo systemctl status athena-verified-backup.service
sudo systemctl list-timers athena-verified-backup.timer
sudo journalctl -u athena-verified-backup.service --since '24 hours ago'
```

Do not declare the operational criterion closed until the operator retains
multiple **actual** timestamped successful timer executions, independently
confirms the off-site failure domain and recoverability, verifies the restored
database in isolation, measures RPO/RTO, and configures an alert for any failed
service or stale successful run. The entry point deliberately reports
`scheduledExecutionVerified=false`, `offsiteLocationVerified=false` and
`productionRecoveryVerified=false`; those facts require external evidence.
The unit uses `ProtectHome=true`: deploy the database under an authorized
service-readable path outside protected home directories. It logs only
sanitized status, backup SHA-256 and conservative policy flags, not secrets
or database paths.

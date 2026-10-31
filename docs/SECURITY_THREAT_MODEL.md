# ATHENA TYCHE — Security Threat Model

Updated: 2026-09-14

## Scope

This threat model covers the v1 backend security boundary for authentication, account recovery, encrypted user profile data, authenticated portfolio data, HTTP response handling and backup/recovery controls. It does not claim that a production deployment, SMTP provider, secret manager or off-site backup target has been operationally verified.

## Assets

- account credentials and active sessions;
- JWT signing secret;
- AES-256-GCM profile encryption keys and historical migration keys;
- password-recovery challenges and SMTP credentials;
- user profile preferences, capital context and declared average purchase prices;
- authenticated portfolio positions and append-only portfolio history;
- SQLite primary database and verified backups.

## Trust boundaries

1. Flutter client to HTTPS backend.
2. Backend process to environment/secret store.
3. Backend process to SQLite storage.
4. Backend recovery flow to SMTP provider.
5. Operator backup process to backup/off-site storage.
6. CI validation to protected release branch.

## Threats and implemented controls

| Threat | Implemented control | Remaining production evidence |
| --- | --- | --- |
| Credential theft / password database disclosure | Argon2 password hashing, no plaintext passwords, login throttling | deployed monitoring / incident response |
| Token theft / replay | signed expiring JWT, unique jti, persistent revocation, session-version invalidation, no-store account responses | production TLS termination verification |
| Cross-user data access | JWT-derived ownership for profile/portfolio, owner-scoped repositories, A/B isolation regressions | final cross-surface E2E acceptance |
| Sensitive profile disclosure at rest | AES-256-GCM, owner/version associated data, exact-version decrypt, integrity failure closes access | production key custody and rotation procedure |
| Key reuse / weak deployment secret configuration | `/api/v1/readiness/security` validates minimum auth-secret strength, AES key shape, key-version/keyring validity and auth/profile key separation without returning values | secret-manager deployment and rotation evidence |
| Recovery-token disclosure | recovery tokens stored only as SHA-256 digests, one-use/expiry, no token logging/fallback | real SMTP delivery verification |
| Recovery channel downgrade | HTTPS public recovery URL and STARTTLS configuration checks | real provider TLS/delivery evidence |
| Browser/proxy caching of account data | `Cache-Control: no-store` and `Pragma: no-cache` on `/api/v1/auth/*` and `/api/v1/user/*` | production reverse-proxy verification |
| Corrupt/tampered encrypted profile | AES-GCM authentication tag; malformed/unknown versions fail closed | operational alerting |
| Backup corruption / unsafe restore | WAL-safe SQLite backup API, SHA-256 manifest, integrity/schema checks, non-destructive restore drill | scheduled and off-site execution evidence |
| Automatic privilege escalation into investment execution | personalization and readiness diagnostics explicitly cannot alter scoring, weighting, learning promotion or trading | human governance remains mandatory |

## Deployment security acceptance contract

The configuration diagnostic may report `ready=true` only when all of these properties hold:

1. `ATHENA_AUTH_SECRET` contains at least 32 bytes.
2. `ATHENA_PROFILE_ENCRYPTION_KEY` decodes to exactly 32 bytes.
3. the profile key version is a positive integer and every historical key has a distinct positive version and valid 32-byte key material.
4. authentication signing material and profile encryption material are not reused.
5. the public recovery URL is HTTPS.
6. recovery SMTP host/from/port configuration is coherent.
7. SMTP username/password are configured together or both omitted.
8. SMTP transport encryption is enabled.

The diagnostic never returns secret values. Even when all checks pass, it must keep `productionDeploymentVerified=false`, `smtpDeliveryVerified=false`, `offsiteBackupVerified=false` and `automaticSecretRotation=false` until external operational evidence exists.

## Required production evidence still open

- secret-manager ownership, access policy and rotation drill;
- removal of historical profile keys after verified migration completion;
- recovery email delivery through the deployed SMTP channel;
- production TLS/reverse-proxy header verification;
- scheduled backup execution and an off-site copy with restore evidence;
- incident-response ownership and alerting;
- protected branch and required status checks.

These items cannot be closed by fixtures or unit tests alone.

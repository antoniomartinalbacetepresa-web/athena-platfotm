# Account privacy lifecycle

This document describes ATHENA TYCHE's current software contract for account closure. It is an engineering/data-lifecycle contract, not a claim of legal compliance or proof of production retention operations.

## Closure authority

`POST /api/v1/auth/close-account` derives the account exclusively from the authenticated bearer token and requires the current password again. A caller cannot select another `user_id`. A successful closure invalidates the account and prior sessions; the original email can no longer resolve to the closed identity.

## Data purged at closure

The identity row keeps only its stable numeric id for referential integrity. Direct identity fields are minimized: the original email is replaced by an `@account.invalid` tombstone, `display_name` is cleared, and the former password hash is replaced by a random unusable credential hash.

If the corresponding tables exist, closure physically deletes the owner's mutable encrypted Profile preferences and current Portfolio positions in the same SQLite transaction as identity anonymization. This includes the encrypted declared average purchase price. A failure to complete the identity update rolls back those deletions rather than leaving a half-closed account.

Password-recovery challenges are invalidated and all sessions are revoked through the existing security services. An inactive account also fails token validation independently of those revocations.

## Data not silently rewritten

Append-only research, recommendation, accounting or owner-scoped portfolio evidence is not deleted or rewritten by the account-closure transaction. Altering an existing hash chain would destroy evidence integrity and could make historical analysis unverifiable. Closed accounts have no authenticated access to that evidence through their former identity.

This retained evidence remains a privacy/readiness boundary rather than a completed compliance claim. Before production readiness can be asserted, ATHENA still needs an approved retention schedule and legal/operational basis for each retained evidence class, plus backup/off-site deletion semantics. Where policy ultimately requires destruction, it must be implemented without pretending that a broken or rewritten append-only chain is valid evidence.

## Backups and deployment boundary

Database backups may contain pre-closure data until the separately governed backup-retention window expires. CI regressions prove live-database behavior only; they do not prove erasure from existing backups, external replicas, logs, SMTP systems or infrastructure snapshots.

Production readiness therefore remains blocked on documented retention periods, deployment secret/key management, scheduled/off-site backup operations, and restore/deletion drills that demonstrate the intended lifecycle in the real environment.

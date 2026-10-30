# Professional Research Cycle — atomic append-only persistence

The POST `/api/v1/recommendations/professional-research/research-cycle` persists a PIT Investment Journal revision and its matching Radar/Journal/Devil's Advocate cycle in **one SQLite write transaction**. Both repositories must use the same database file. Schema initialization finishes before the write transaction; a single `BEGIN IMMEDIATE` serializes the journal lineage check, journal append, lineage revalidation, and cycle append. Any failure rolls back both writes. Existing immutable revisions remain immutable.

This closes the partial-write failure mode where a new Journal revision could previously survive a failed cycle append, making a subsequent retry ambiguous. It does **not** prove durable external/WORM custody, that source data were actually available before the research cutoff, operational OOS performance, or production authorization. No automatic trading, scoring promotion, weighting or learning is introduced.

Acceptance requires the existing full package-integrity and lineage tests plus a regression that forces the cycle append to fail after the Journal write, verifies zero committed Journal revisions, and rejects repositories configured against different SQLite files. These are controlled CI regressions, not evidence from the operational database.

## Canonical journal integrity at the storage boundary

Before any append (including an append inside the paired cycle transaction), the repository now rebuilds the frozen Investment Journal snapshot and checks its exact SHA-256 and canonical API contract. A forged dataclass with a plausible hash or retrospectively changed thesis is rejected **before insertion**. During lineage reads, the repository also compares the entire persisted snapshot against the canonical reconstructed payload, including its policy fields; changing an unhashed policy field or adding an unauthorized field cannot silently pass verification. Regression cases prove a rejected forged revision leaves the journal usable and that altered persisted contracts fail closed.

This is an internal consistency and tamper-detection guarantee, **not** an independently witnessed/WORM record, proof of the truth of external sources, production acceptance, or permission for trading or weighting. Strict canonical-contract verification may require an explicitly versioned migration if legacy persisted snapshots used a different policy schema; do not silently reinterpret or rewrite historical records.

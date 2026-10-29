# Professional Research Cycle — atomic append-only persistence

The POST `/api/v1/recommendations/professional-research/research-cycle` persists a PIT Investment Journal revision and its matching Radar/Journal/Devil's Advocate cycle in **one SQLite write transaction**. Both repositories must use the same database file. Schema initialization finishes before the write transaction; a single `BEGIN IMMEDIATE` serializes the journal lineage check, journal append, lineage revalidation, and cycle append. Any failure rolls back both writes. Existing immutable revisions remain immutable.

This closes the partial-write failure mode where a new Journal revision could previously survive a failed cycle append, making a subsequent retry ambiguous. It does **not** prove durable external/WORM custody, that source data were actually available before the research cutoff, operational OOS performance, or production authorization. No automatic trading, scoring promotion, weighting or learning is introduced.

Acceptance requires the existing full package-integrity and lineage tests plus a regression that forces the cycle append to fail after the Journal write, verifies zero committed Journal revisions, and rejects repositories configured against different SQLite files. These are controlled CI regressions, not evidence from the operational database.

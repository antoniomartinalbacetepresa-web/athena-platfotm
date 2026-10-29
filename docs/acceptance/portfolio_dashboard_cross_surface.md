# Portfolio cross-surface acceptance

The Dashboard to Portfolio acceptance verifies named-route navigation and confirms that guest presentation does not grant authenticated synchronization authority.

The Profile to Portfolio lifecycle acceptance additionally verifies that a remotely confirmed logout removes local Portfolio authority before navigation continues, guest Portfolio controls remain disabled, and a later replacement owner acquires only the new session authority. No Profile-derived capital, currency, position or credential is copied across owners by this acceptance path.

These tests are software acceptance evidence only. They do not claim production key custody, SMTP delivery, historical-market coverage, external market-weighting approval, longitudinal OOS evidence or any other operational evidence.

### Authenticated cloud-sync lifecycle

The presentation controller invalidates its pending generation on disposal. A late success or failure from a previously mounted Portfolio surface must not notify a disposed controller, publish owner-scoped sync status, or start a new write through that disposed instance. In-flight service operations retain their own authority-version checks; this lifecycle guard is not evidence of two-owner deployed acceptance.

### Route disposal and owner-scoped asynchronous work

A disposed Portfolio route cannot start a cloud write after a delayed local
positions snapshot resolves. The authenticated holdings controller refuses
new reads and mutations after disposal and clears its in-memory positions;
its FX valuation controller invalidates in-flight results and ignores late
success/failure without notifying disposed listeners. A completed sync status
is shown only while the same mounted route and authority generation remain
current. These are Flutter lifecycle and authorization-boundary regressions,
not deployed two-owner HTTPS acceptance or operational investment evidence.

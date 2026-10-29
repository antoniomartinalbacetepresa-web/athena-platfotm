# Portfolio cross-surface acceptance

The Dashboard to Portfolio acceptance verifies named-route navigation and confirms that guest presentation does not grant authenticated synchronization authority.

The Profile to Portfolio lifecycle acceptance additionally verifies that a remotely confirmed logout removes local Portfolio authority before navigation continues, guest Portfolio controls remain disabled, and a later replacement owner acquires only the new session authority. No Profile-derived capital, currency, position or credential is copied across owners by this acceptance path.

These tests are software acceptance evidence only. They do not claim production key custody, SMTP delivery, historical-market coverage, external market-weighting approval, longitudinal OOS evidence or any other operational evidence.

### Authenticated cloud-sync lifecycle

The presentation controller invalidates its pending generation on disposal. A late success or failure from a previously mounted Portfolio surface must not notify a disposed controller, publish owner-scoped sync status, or start a new write through that disposed instance. In-flight service operations retain their own authority-version checks; this lifecycle guard is not evidence of two-owner deployed acceptance.

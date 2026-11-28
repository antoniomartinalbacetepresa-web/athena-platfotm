# Investors: session-only SEC 13F CIK exploration

The Investors route accepts up to five comma-separated SEC CIKs (1–10 decimal digits each), with manual submit and clear. A user can therefore explore verified public 13F filings without a build-time CIK list. This is an **informational read-only** feature; it does not create orders, change ATHENA scores, approve weighting, learn from holdings or write to the owner's Portfolio.

Input is validated before any request. Invalid or excessive input immediately revokes the previous displayed cohort and makes **no** new SEC/backend request. Duplicate CIKs are queried once in input order. A new or repeated submission replaces the entire panel request generation, so a late response from an older query cannot regain authority. A failed member invalidates the whole requested cohort; provider errors and credentials are not rendered.

CIKs entered here are held only in widget memory, not persisted to preferences, analytics, local storage or the server as a personal watchlist. Requests still reach the existing backend SEC endpoint; operators must apply appropriate backend rate limits and official SEC usage policy. The Dashboard's independently configured investor panel is unchanged.

Widget regressions cover invalid input, the five-CIK bound, duplicate suppression, error sanitization, explicit clearing and stale-request replacement. These are **engineering tests**, not deployed HTTPS/Chromium acceptance, proof of SEC provider authenticity or proof of a live 13F filing. The deployed guest research acceptance and its exact-SHA prerequisites remain open until a real staging deployment is available.

"""VA Lighthouse (developer.va.gov) integration — veteran-consented API access.

The veteran signs in at VA.gov (Login.gov / ID.me) and consents; every call this
package makes runs on a token issued ON THEIR BEHALF. Legal lane: this is the
veteran acting through software they operate themselves (exactly like VA.gov's
own UI) — nothing is filed or changed without their explicit, per-action
confirmation, and every mutation is audited.

Modules:
  lighthouse — OAuth2 auth-code + PKCE (S256) against the per-API Lighthouse
               authorization servers, plus the authenticated HTTP calls.
  normalize  — PURE normalizers for Lighthouse responses + the diff-style
               suggestion builder (/va/sync previews; NEVER auto-applies).
  service    — token store helpers on the RLS-fenced va_connections table:
               lookup, refresh-when-expired, needs_reconnect bookkeeping.
  legal      — the plain-language terms/privacy markdown served at /api/legal
               (a VA production-access prerequisite).

Tokens are per-veteran credentials: RLS-fenced at rest, never logged.
"""

# Rule-version governance

`GET /api/release` is the public, privacy-safe rule-version surface. It reports the
current version, effective KB verification date, changelog, and SHA-256 content
fingerprint. The machine-readable source is
`backend/app/kb/data/rule_versions.json`; the release inventory is
`backend/release-manifest.json`.

For every rule-bearing change:

1. Cite current primary eCFR/VA sources and record the verified-as-of date.
2. Add a changelog entry with a new rule version and plain-language impact summary.
3. Recompute the fingerprint, update the release manifest, and never reuse a version.
4. Add or update de-identified golden cases and complete an evaluation card.
5. Obtain the required VA-accredited/domain and legal/privacy review before deployment.
6. Verify `/api/release`, `valor_release_info`, stale-KB gating, and the public canary.

The initial entry is an engineering governance baseline. It does not itself certify
legal accuracy or replace current-rule review.

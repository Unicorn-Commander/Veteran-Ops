# Valor-Ops release, migration, and rollback checklist

## Code-controlled gate

- [ ] Worktree is clean; intended branch and reviewed commit are recorded.
- [ ] `backend/release-manifest.json` version matches `app.__version__`.
- [ ] Rule and benefits fingerprints match; every rule change has a changelog entry.
- [ ] Full backend, real PostgreSQL/RLS, golden evaluation, frontend unit/build, and
      desktop/mobile Playwright gates pass.
- [ ] Prometheus rules pass `promtool check rules` and both compose files render.
- [ ] `scripts/valor-backup-restore-smoke.sh` passes with synthetic data only.
- [ ] `scripts/release-hygiene.sh` passes; no raw agent/session transcript is shipped.
- [ ] No `.env`, credential, private key, real document, or veteran fixture is staged.

## Operator preflight

**Promotion blocker:** do not deploy while `/api/release` reports a KB status other
than `current`. Advance the verification date only after a real curated primary-source
review, changelog entry, evaluation, and required approval.

- [ ] Rotate any credential ever committed to repository history; deleting it from the
      current file is not rotation.
- [ ] If a raw agent transcript was ever pushed, remove it from public upstream history
      through an approved history rewrite and invalidate exposed session/request metadata.
      Replacing the current file does not remove prior Git objects or downstream clones.
- [ ] Capture current commit, image digest, `/api/release`, rule version, KB verification
      date, and schema revision in the change record.
- [ ] Confirm the current KB is not stale and required primary-source review is signed.
- [ ] Create a backup and run disposable restore verification before migration.
- [ ] Confirm disk headroom, database connections, worker status, alert routing, and a
      tested maintenance/rollback communication path.

## Additive migration

`init_db()` owns forward-only additive schema changes and RLS reconciliation. There is
no destructive down migration.

- [ ] Quiesce risky writes or place ingress in maintenance mode for the migration window.
- [ ] Gracefully stop/drain the analysis worker; record active queue counts.
- [ ] Start the new API so `init_db()` applies the schema as the NOBYPASSRLS app role.
- [ ] Confirm `analysis_runs` has ENABLE + FORCE RLS and `workspace_isolation`.
- [ ] Confirm legacy active analysis rows were promoted or explicitly failed, never lost.
- [ ] Start the matching worker release and confirm heartbeat, queue reconciliation, and
      `/api/readyz` before restoring ingress.

## Post-release

- [ ] `/api/healthz`, `/api/readyz`, `/api/meta`, `/api/release`, and `/metrics` agree.
- [ ] Public synthetic canary passes and its metric timestamp advances.
- [ ] Queue depth/age, retries, failures, expired leases, unsynced runs, DB, KB, 5xx, and
      latency alerts are normal.
- [ ] Run one approved synthetic authenticated journey; do not use a veteran account.
- [ ] Observe at least one worker heartbeat interval before closing the change.

## Rollback

1. Disable ingress and gracefully stop API/worker processes from the bad release.
2. Record queue aggregates and logs without payloads. Do not run an older worker against
   active jobs created by a newer incompatible schema.
3. If only application behavior regressed and the schema is backward-compatible, deploy
   the recorded prior image and rerun readiness/RLS/synthetic gates.
4. If data or schema state must be reversed, restore the pre-release verified DB and
   uploads set together. Do not improvise destructive SQL to simulate a down migration.
5. Recreate the NOBYPASSRLS app role, run the prior compatible `init_db()`, and verify
   FORCE-RLS before enabling ingress.
6. Reconcile or explicitly communicate jobs accepted after the backup RPO; never claim
   completion when those jobs or uploads are absent from the restored set.

## Work outside this repository

Production deployment, DNS/TLS, Center Deep scrape/Alertmanager wiring, credential
rotation, legal/privacy approval, VA Lighthouse production access, current-rule domain
review, and live-user acceptance remain explicit operator or accredited-review work.

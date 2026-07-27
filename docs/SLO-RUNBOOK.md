# Valor-Ops SLO and incident runbook

These are initial engineering objectives for a privacy-sensitive self-help product.
They are not legal, clinical, or VA accuracy certifications. Ratify targets after 30
days of production measurements; do not weaken stale-knowledge or RLS controls to hit
an availability number.

## Service objectives

| Signal | Initial objective | Measurement |
|---|---:|---|
| Public/API availability | 99.9% per 30 days | `valor_synthetic_journey_success` plus non-5xx HTTP requests |
| Interactive API latency | p95 under 1.5s over 10m | `valor_http_request_duration_seconds` (long analysis runs are async) |
| Database availability | 99.95% per 30 days | `valor_dependency_up{dependency="database"}` |
| Knowledge safety | zero new guarded guidance while stale | `valor_kb_status`; the application fail-closes guarded routes |
| Freshness visibility | unknown for less than 30m | `valor_kb_status{status="unknown"}` |
| Analysis dispatch | oldest active job under 15m while KB is current | queue age, worker heartbeat, retry and lease gauges |
| Queue/run convergence | no unsynchronized run for more than 5m | `valor_analysis_unsynced_runs` |
| Public synthetic journey | successful at least every 5m | canary textfile metrics |
| Backup RPO / restore RTO | 24h / 4h | daily verified backup; quarterly disposable restore drill |

A 99.9% monthly availability objective allows about 43 minutes of unavailability.
Create an incident at 25% budget consumption and freeze risky releases at 75%.

## Privacy rules during incidents

- Never paste request bodies, document names, prompts, exception text, database rows,
  OAuth tokens, or user identifiers into alerts or tickets.
- Use aggregate metrics, opaque run IDs only when access is approved, and exception
  classes rather than messages.
- Do not query a veteran workspace to make a canary pass. Production authenticated
  testing requires a separately approved synthetic tenant with no real records.
- Never bypass FORCE-RLS, stale-KB gating, or the legal disclaimer as mitigation.

## API or database outage

1. Confirm `/api/healthz`, `/api/readyz`, and `valor_dependency_up` disagree or fail.
2. Check container state and aggregate logs without dumping environment variables:
   on app-host, run
   `docker compose -p valor-ops -f infrastructure/docker-compose.app-host.yml ps`.
3. Verify PostgreSQL storage, connections, disk, and `pg_isready`. Do not run a
   destructive repair while backups are unverified.
4. If a recent release caused the outage, follow [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md)
   and use the verified restore artifact when data rollback is necessary.
5. After recovery, confirm readiness, public canary, RLS integration tests, queue
   convergence, and one operator-approved synthetic workflow.

## Release manifest invalid

1. Stop the release. Readiness intentionally fails when the application version,
   rule inventory, benefits inventory, or rule changelog does not match the committed
   manifest.
2. Run the release-focused tests and inspect only file paths and SHA-256 fingerprints;
   these artifacts contain no veteran data.
3. If curated rule content changed, require primary-source review, update the rule
   version and changelog, and rerun golden evaluations before updating fingerprints.
4. Do not edit a fingerprint merely to make readiness green. Establish why content
   changed and record the review in an evaluation card first.

## Stale or unknown knowledge

1. Treat `stale` as a safety event, not an uptime event. Guarded analysis should return
   `503 kb_stale`; historical records remain readable.
2. Compare the detected Title 38 amendment date with the persisted KB verification
   date and open refresh signal. Do not clear it based on a superficial date bump.
3. Have the changed criteria reviewed against primary eCFR/VA sources and record the
   rule-version changelog entry and evaluation card.
4. Run deterministic golden evaluations, focused rule tests, and fingerprint checks.
5. Apply the curated refresh through the existing reviewed KB workflow. Confirm the
   signal resolves and `valor_kb_status{status="current"}` becomes 1.

## Analysis worker or queue

1. Check workers alive/stale, queue depth/age, expired leases, retries, recent failures,
   and unsynchronized runs. Do not inspect veteran payloads; the queue is metadata-only.
2. Confirm the dedicated worker container is running and uses the same release as the
   API. A worker restart is safe: leases expire, retries are bounded, and reconciliation
   is idempotent.
3. If the KB is stale, queue age is expected to rise; resolve knowledge review instead
   of forcing jobs through.
4. For expired leases, verify database latency and worker heartbeat cadence. Repeated
   failures require code/model-service diagnosis before increasing retry limits.
5. Page immediately for sustained `valor_analysis_unsynced_runs`; the user-visible RLS
   run and dispatch state must converge before declaring recovery.

## Synthetic journey

Run every five minutes from an operator host or Center Deep node-exporter textfile
collector:

```bash
python3 scripts/valor-canary.py \
  --base-url https://valor.magicunicorn.dev \
  --prometheus-textfile /var/lib/node_exporter/textfile_collector/valor-canary.prom \
  --json-output /var/lib/valor-canary/last-result.json
```

The canary sends four public GET requests and records no response bodies in metrics.
It validates liveness, readiness, version/release consistency, KB status, and content
fingerprints. CI separately runs the authenticated Analysis Center journey with mocked,
synthetic API fixtures. A real production auth canary remains an operator/privacy
decision and must use a dedicated synthetic tenant.

## Backup or restore failure

1. A backup is successful only when the custom dump, uploads archive, manifest, and
   checksum inventory exist and structural validation passed.
2. Do not overwrite the last known-good set after a failed run. Investigate disk,
   container access, age recipient, and remote credential-chain errors.
3. Run `scripts/valor-restore-verify.sh` against the candidate set. It restores into a
   disposable container, verifies critical tables and FORCE-RLS, and never prints rows.
4. Run `scripts/valor-backup-restore-smoke.sh` after tooling changes and at least
   quarterly on the deployed host with synthetic fixtures.
5. For a real disaster recovery, restore uploads and DB, recreate the non-superuser app
   role, run `init_db()`, and verify RLS before enabling ingress.

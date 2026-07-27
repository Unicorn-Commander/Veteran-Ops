# Valor-Ops operations (Wave 15)

Production hardening for a live system that holds veterans' PII (claim data + uploaded
documents). The application host is `app-host`, dir `/srv/veteran-ops/valor-ops`, using
`docker compose -p valor-ops -f infrastructure/docker-compose.app-host.yml`. edge-host is
the TLS/Traefik edge only: its file-provider route forwards the public Valor hosts over
the tailnet to `app-host.internal:8400`.

## Durable analysis worker

Comprehensive analyses are committed to PostgreSQL before the API returns. Production
compose runs `analysis-worker` separately from the API; do not remove it or enable the
API's embedded worker at the same time unless temporary extra consumers are intended.
Multiple workers are safe because claims use row locking, expiring leases, and fencing
tokens. An API or worker restart leaves the job queued or recoverable.

`/readyz` reports aggregate queue counts, expired leases, unsynchronized run rows,
and live worker heartbeats.
Production sets `ANALYSIS_WORKER_REQUIRED=true`, so readiness fails when no recent
worker heartbeat exists. Alert on `analysis_worker=unavailable`, any expired lease,
any sustained `unsynced_runs`, or sustained queued growth. Cancellation is cooperative
and is observed on the worker's heartbeat interval.

The global `analysis_jobs` and `analysis_workers` tables contain operational UUIDs and
timings only. Veteran results remain in FORCE-RLS `analysis_runs`; worker execution
always re-enters the user's workspace-scoped database session.

## Backups — ALL stateful surfaces

`scripts/valor-backup.sh` (cron: `30 3 * * *`) backs up **every** stateful surface —
DB-only is not enough (a `docker compose` recreate can wipe a named volume; a veteran's
un-exported documents would be gone). Each run produces, with 30-day local retention +
an optional off-host copy configured outside the repository:

| Artifact | Source | Notes |
|---|---|---|
| `valor_db_<timestamp>.dump` | custom-format `pg_dump` of `valor` (as `postgres`) | Full schema incl. RLS policies + rows. Verified with `pg_restore --list`. |
| `valor_uploads_<timestamp>.tar.gz` | `valor-ops-backend:/app/uploads` | Veteran documents; archive is structurally validated. |
| `valor_env_<timestamp>.env.age` | `infrastructure/.env` | Optional **age**-encrypted environment; private key remains off-host. |
| `valor_backup_<timestamp>.manifest/.sha256` | release identity + artifact inventory | Verifies artifact integrity without exposing row or file contents. |

**If you add a new `volumes:` entry to the compose file, add it to the backup script.**

The script contains no remote credentials. Set `VALOR_BACKUP_REMOTE_URI` and optional
`VALOR_BACKUP_S3_ENDPOINT` in `~/.config/valor-ops/backup.env`; AWS credentials come
from the CLI's standard credential chain or instance identity.

The live `infrastructure/.env` and, when created, external `backup.env` contain secrets
and must be owned by the deployment account with mode `0600`; the containing
`~/.config/valor-ops` directory must be `0700`. Enforce and verify permissions without
printing either file before starting Compose or enabling remote backup:

```bash
install -d -m 700 /srv/veteran-ops/.config/valor-ops
chmod 600 /srv/veteran-ops/valor-ops/infrastructure/.env
if [ -e /srv/veteran-ops/.config/valor-ops/backup.env ]; then
  chmod 600 /srv/veteran-ops/.config/valor-ops/backup.env
  stat -c '%a %U:%G %n' /srv/veteran-ops/.config/valor-ops/backup.env
fi
stat -c '%a %U:%G %n' /srv/veteran-ops/valor-ops/infrastructure/.env
```

**Credential response:** an older tracked backup script contained embedded object-store
credentials. Revoke/rotate them before the next release and use an approved history
remediation plus secret scan. Removing values from the current file does not invalidate
them or erase them from Git history. Never paste the old values into an issue or log.

**Research-artifact response:** an older tracked research file contained a raw agent
session export. It is replaced by a curated public-source brief, but any already-pushed
copy still requires approved upstream history remediation and session/request metadata
invalidation. `scripts/release-hygiene.sh` blocks common transcript markers and credential
formats without printing matched values.

### Restore verification

```bash
scripts/valor-restore-verify.sh \
  --db-dump valor_db_<timestamp>.dump \
  --uploads valor_uploads_<timestamp>.tar.gz \
  --checksums valor_backup_<timestamp>.sha256
```
This restores into a disposable pgvector container, validates critical tables,
`analysis_runs` FORCE-RLS and workspace policy, and inspects only aggregate counts.
Run `scripts/valor-backup-restore-smoke.sh` for the credential-free synthetic drill.
For disaster recovery, decrypt the environment only into the protected deployment
path, restore DB and uploads together, recreate the NOBYPASSRLS app role, and run
`init_db()` before enabling ingress.

## Edge rate-limiting (Traefik)

The auth surface (`/api/auth/*` — login / register / password / verify) is rate-limited
at the edge-host edge by a higher-priority Traefik sub-router (`valor-ops-auth`) with
middleware `valor-auth-rl`: ~8 req/s sustained, burst 20, **per real client IP**
(`Cf-Connecting-Ip`, since this router only sees Cloudflare traffic). Generous enough
never to bother a real person; throttles credential-stuffing / brute-force /
account-enumeration. The live route is managed outside this repository at
`/srv/veteran-ops/UC-Cloud-production/extensions/traefik-edge-host/dynamic/valor-ops.yml` on
edge-host; app-host intentionally carries no Traefik labels or public `web` network. A
throttled caller gets `429`. Coordinate edge changes with the edge-host route and validate
the forwarded app-host service before reloading Traefik.

## Health watchdog

`scripts/valor-watchdog.sh` (cron: `*/5 * * * *`) polls `/api/meta` and logs + alerts on a
**state change** (up→down, down→up), so an outage pings once, not every tick. It always
logs (Loki/centerdeep can ingest) and additionally emails via Postmark **iff**
`~/.config/valor-ops/watchdog.env` supplies `POSTMARK_TOKEN` + `ALERT_FROM` + `ALERT_TO`
(the `From` must be a Postmark-verified sender). No config → log-only, no failure.

## Observability → centerdeep (canonical)

Per the ecosystem convention, centerdeep is the one observability hub — **do not** stand
up a per-node Prometheus/Grafana here. The app is scrape-ready:

- Backend exposes **`/metrics`** (Prometheus): route-templated HTTP count/latency,
  DB/worker dependencies, KB status, queue state/age, worker heartbeats, expired leases,
  retries/failures, reconciliation state, and release identity. It is **not** exposed through the public edge (the
  frontend proxies only `/api`) — reach it inside the compose network at
  `valor-ops-backend:8000/metrics`.

### To wire centerdeep (Aaron — shared-infra side)

1. Make `/metrics` reachable to centerdeep over the tailnet — e.g. publish the backend
   on the Tailscale interface (`ports: ["100.x.x.x:9109:8000"]`) or add a small
   metrics-only bind; keep it OFF `0.0.0.0`.
2. Add a scrape job to centerdeep's `prometheus.yml`:
   ```yaml
   - job_name: valor-ops
     metrics_path: /metrics
     static_configs: [{ targets: ["<app-host-tailscale-ip>:9109"] }]
   ```
   (open the port in the headscale ACL, tag:admin — see the Headscale ACL workflow.)
3. Load `infrastructure/monitoring/valor-alerts.yml` and validate it with `promtool`.
4. Schedule `scripts/valor-canary.py` every five minutes and expose its atomic textfile
   metrics through node_exporter. See `docs/SLO-RUNBOOK.md` for objectives and response.

Until then, the local watchdog above is the interim alerting.

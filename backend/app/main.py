"""Rating Raider API — application entrypoint.

Router inclusion is deliberately tolerant: auth + sso (BACKEND-CORE) are imported
directly; the feature routers (ROUTERS agent) are included via a per-module
try/except loop so the app boots before, during, and after they land.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

# Prometheus metrics (Wave 15 — observability). Optional import so the app runs even
# where the dep isn't installed yet (e.g. a bare local test env); metrics are simply
# disabled in that case. In prod (requirements pins prometheus-client) they're on.
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _MET_REQS = Counter(
        "valor_http_requests_total", "HTTP requests", ["method", "path", "status"]
    )
    _MET_LAT = Histogram(
        "valor_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
    )
    _MET_DEP = Gauge(
        "valor_dependency_up", "Dependency availability (1=up, 0=down)", ["dependency"]
    )
    _MET_KB = Gauge(
        "valor_kb_status", "Knowledge status as a one-hot gauge", ["status"]
    )
    _MET_ANALYSIS_JOBS = Gauge(
        "valor_analysis_jobs", "Durable analysis jobs by state", ["status"]
    )
    _MET_QUEUE_AGE = Gauge(
        "valor_analysis_queue_oldest_seconds",
        "Age in seconds of the oldest active durable analysis job",
    )
    _MET_WORKERS_ALIVE = Gauge(
        "valor_analysis_workers_alive", "Analysis workers with a recent heartbeat"
    )
    _MET_WORKERS_STALE = Gauge(
        "valor_analysis_workers_stale", "Analysis workers whose heartbeat is stale"
    )
    _MET_EXPIRED_LEASES = Gauge(
        "valor_analysis_expired_leases", "Analysis jobs with an expired active lease"
    )
    _MET_UNSYNCED_RUNS = Gauge(
        "valor_analysis_unsynced_runs", "Queue transitions awaiting RLS run reconciliation"
    )
    _MET_FAILED_RECENT = Gauge(
        "valor_analysis_failed_recent", "Analysis jobs that failed in the last hour"
    )
    _MET_RETRIED_JOBS = Gauge(
        "valor_analysis_retried_jobs", "Retained analysis jobs that required a retry"
    )
    _MET_RELEASE = Gauge(
        "valor_release_info",
        "Build, rules, and knowledge release identity",
        ["version", "release_id", "source_revision", "rule_version", "kb_version"],
    )
    _METRICS_ON = True
except Exception:  # noqa: BLE001 — observability is never allowed to break serving
    _METRICS_ON = False

from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from . import overrides
from .config import settings
from .db import engine, init_db
from .routers import auth, sso
from .schemas import LegalOut, MetaOut, ReleaseOut

log = logging.getLogger("veteran_ops")
logging.basicConfig(level=logging.INFO)

# The global legal-lane disclaimer (docs/BUILD-SPEC.md, "Legal lane"). Surfaced by
# GET /api/meta, rendered by the frontend footer + first-run acknowledgment, and
# echoed by the analysis endpoints. Keep this the ONE place the string lives.
DISCLAIMER = (
    "Veteran-Ops is self-help educational software; Rating Raider is your claims agent "
    "inside the app. Neither is legal advice, a VA-accredited representative or agent, "
    "nor affiliated with the U.S. Department of Veterans Affairs. For free help filing "
    "or appealing, use a VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The "
    "American Legion, or your state/county veterans office. Verify current rating "
    "criteria at eCFR / VA.gov — regulations change."
)

# Core infrastructure routers (always present).
CORE_ROUTERS = [
    "admin_services",
    "admin_kb",
]

# Feature router modules owned by the ROUTERS agent (see BUILD-SPEC file ownership).
ROUTER_MODULES = CORE_ROUTERS + [
    "profile",
    "conditions",
    "evidence",
    "checklist",
    "rating",
    "kb",
    "kb_admin",
    "analysis",
    "packet",
    "filing",
    "glitter",
    "documents",
    "records",
    "va",
    "readiness",
    "raider",
    "itf",
    "deadlines",
    "symptomlog",
    "buddy",
    "cp",
    "form526",
    "forms",
    "nexus",
    "statement",
    "appeals",
    "strategy",
    "tdiu",
    "concurrent_pay",
    "dependency",
    "account",
    "corrections",
    "workspaces",
    "orgs",
    "invites",
    "benefits",
    "entitlements",
    "credits",
    "cases",
    "billing",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    freshness_task: asyncio.Task | None = None
    deep_dive_task: asyncio.Task | None = None
    analysis_worker_task: asyncio.Task | None = None
    analysis_worker_stop: asyncio.Event | None = None
    # Refuse to serve with a default/weak signing key (would let anyone forge a
    # token for any user and read every veteran's data).
    if (
        settings.jwt_secret in ("", "change_me_to_a_long_random_string")
        or len(settings.jwt_secret) < 24
    ):
        raise RuntimeError(
            "JWT_SECRET is unset or a known default — set a strong, unique JWT_SECRET (>=24 chars)."
        )

    # Wait for Postgres, then create tables + apply RLS policies. Fail hard if the
    # DB never comes up so the container restarts instead of serving 500s.
    last_exc: Exception | None = None
    for attempt in range(1, 11):
        try:
            await init_db()
            log.info("Database initialized (tables + RLS).")
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("DB init attempt %s/10 failed: %s", attempt, exc)
            await asyncio.sleep(2)
    else:
        raise RuntimeError(f"Database init failed after retries: {last_exc}")

    # Warm the service-override cache so persisted admin overrides (gateway URL,
    # models, privacy mode) apply immediately on boot — not only after the next
    # admin save. Non-fatal: on any error the app serves with pure env defaults.
    try:
        async with AsyncSession(engine) as _ovr_session:
            await overrides.refresh_cache(_ovr_session)
    except Exception:  # noqa: BLE001 — must serve even if the override table can't be read
        log.exception("service-override cache warmup skipped")

    # Unstick docs left in 'processing' after a prior worker death / hung OCR-LLM
    # (in-process asyncio has no lease heartbeats). Customer-safe self-heal on boot.
    try:
        from .intake.process import recover_stuck_processing

        n = await recover_stuck_processing()
        if n:
            log.warning("Startup recovered %s stuck processing document(s).", n)
    except Exception:  # noqa: BLE001 — never block boot
        log.exception("stuck-processing recovery skipped")

    # Seed the KB card corpus (idempotent; embeds via bge-m3). Off the critical path
    # so a slow embeddings endpoint can't delay readiness; grounding lights up once
    # it completes (and self-heals on the next boot if it fails). The module may not
    # exist yet — the ROUTERS agent ships backend/app/kb/.
    try:
        from .kb.seed import seed_kb  # type: ignore[import-not-found]

        asyncio.create_task(seed_kb())
    except ImportError:
        log.info("KB seed module not present yet — skipping seed.")
    except Exception:  # noqa: BLE001 — the app must serve even if seeding can't start
        log.exception("KB seeding failed to start")

    # KB QA (non-fatal): WARN for any authored rating-criteria tier above the
    # VA max-ratings dataset ceiling for its diagnostic code.
    try:
        from .kb.store import validate_kb_max_ratings

        validate_kb_max_ratings()
    except Exception:  # noqa: BLE001
        log.exception("KB max-rating validation failed to run")

    # eCFR freshness: immediate non-blocking check, then a lightweight periodic loop.
    # It updates only cached metadata and operational refresh-needed signals.
    try:
        from .kb import freshness

        freshness_task = asyncio.create_task(freshness.run_periodic_checks())
    except Exception:  # noqa: BLE001
        log.exception("KB freshness check failed to start")

    # Proactive exhaustive-rating sweep.  Its own config gate defaults OFF and
    # returns immediately; keeping the lifecycle beside freshness makes shutdown
    # cancellation explicit and testable.
    try:
        from .firm.jobs import run_periodic_sweeps

        deep_dive_task = asyncio.create_task(run_periodic_sweeps())
    except Exception:  # noqa: BLE001
        log.exception("Deep-dive schedule failed to start")

    # Durable DB-backed comprehensive worker. Local/dev defaults to embedded; the
    # production compose disables this copy and runs the same loop in a dedicated
    # restartable worker container.
    if settings.analysis_worker_enabled:
        try:
            from .analysis.worker import run_worker_loop

            analysis_worker_stop = asyncio.Event()
            analysis_worker_task = asyncio.create_task(
                run_worker_loop(stop_event=analysis_worker_stop)
            )
        except Exception:  # noqa: BLE001
            log.exception("Durable analysis worker failed to start")
    try:
        yield
    finally:
        if analysis_worker_task is not None:
            if analysis_worker_stop is not None:
                analysis_worker_stop.set()
            try:
                await asyncio.wait_for(analysis_worker_task, timeout=10)
            except TimeoutError:
                analysis_worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await analysis_worker_task
            except Exception:  # noqa: BLE001 - shutdown still cleans other tasks.
                log.exception("Durable analysis worker stopped with an error")
        if deep_dive_task is not None:
            deep_dive_task.cancel()
            with suppress(asyncio.CancelledError):
                await deep_dive_task
        if freshness_task is not None:
            freshness_task.cancel()
            with suppress(asyncio.CancelledError):
                await freshness_task


app = FastAPI(
    title="Rating Raider API",
    version=__version__,
    description=(
        "Self-service VA disability compensation tool — the veteran always drives; "
        "the app informs and organizes."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityAndFreshnessMiddleware:
    """Apply browser protections and stop stale-law synthesis without buffering.

    Record management and historical results remain usable in degraded mode; only
    routes that calculate new KB-backed guidance are unavailable until a curated
    refresh catches up with the detected Title 38 amendment.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from .kb import freshness
        from .kb.guard import guards_path

        kb = freshness.cached_effective_freshness()
        path = scope.get("path", "")

        async def send_with_security_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault(
                    "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
                )
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("X-Knowledge-Status", str(kb["status"]))
                if path.startswith("/api/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        if kb["stale"] is True and guards_path(scope["method"], path):
            response = JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "detail": (
                        "Rating criteria are temporarily unavailable while a detected "
                        "Title 38 update is reviewed. Your records and prior results remain available."
                    ),
                    "code": "kb_stale",
                    "kb_verified_as_of": kb["kb_verified_as_of"],
                    "title38_latest_amended_on": kb.get("title38_latest_amended_on"),
                },
                headers={"Retry-After": "3600"},
            )
            await response(scope, receive, send_with_security_headers)
            return

        await self.app(scope, receive, send_with_security_headers)


app.add_middleware(SecurityAndFreshnessMiddleware)


if _METRICS_ON:
    async def _refresh_operational_metrics() -> None:
        """Refresh DB-backed gauges at scrape time without affecting request serving."""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            _MET_DEP.labels("database").set(1)
        except Exception:  # noqa: BLE001 - the metric reports the failure.
            _MET_DEP.labels("database").set(0)

        try:
            from .analysis.jobs import queue_health

            queue = await queue_health()
            _MET_DEP.labels("analysis_queue").set(1)
            _MET_DEP.labels("analysis_worker").set(
                1 if queue["workers_alive"] > 0 else 0
            )
            for job_status, count in queue["status_counts"].items():
                _MET_ANALYSIS_JOBS.labels(job_status).set(count)
            _MET_QUEUE_AGE.set(queue["oldest_active_seconds"])
            _MET_WORKERS_ALIVE.set(queue["workers_alive"])
            _MET_WORKERS_STALE.set(queue["workers_stale"])
            _MET_EXPIRED_LEASES.set(queue["expired_leases"])
            _MET_UNSYNCED_RUNS.set(queue["unsynced_runs"])
            _MET_FAILED_RECENT.set(queue["failed_recent"])
            _MET_RETRIED_JOBS.set(queue["retried_jobs"])
        except Exception:  # noqa: BLE001 - preserve the last queue values for diagnosis.
            _MET_DEP.labels("analysis_queue").set(0)
            _MET_DEP.labels("analysis_worker").set(0)

        try:
            from .kb import freshness
            from .release import release_snapshot

            kb = await freshness.effective_freshness()
            for kb_status in ("current", "stale", "unknown"):
                _MET_KB.labels(kb_status).set(1 if kb["status"] == kb_status else 0)
            snapshot = release_snapshot(
                kb_verified_as_of=kb.get("kb_verified_as_of"),
                kb_status=kb["status"],
            )
            _MET_DEP.labels("release_manifest").set(
                1 if snapshot["manifest_valid"] else 0
            )
            _MET_RELEASE.clear()
            _MET_RELEASE.labels(
                snapshot["version"],
                snapshot["release_id"],
                snapshot["source_revision"],
                snapshot["rules"]["version"],
                snapshot["kb"]["version"],
            ).set(1)
        except Exception:  # noqa: BLE001 - release metadata must not break a scrape.
            _MET_DEP.labels("release_manifest").set(0)
            log.warning("release/knowledge metrics refresh failed", exc_info=True)

    class PrometheusMiddleware:
        """Record route-template request metrics without buffering ASGI responses."""

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            started = time.perf_counter()
            response_status = status.HTTP_500_INTERNAL_SERVER_ERROR

            async def send_with_status(message: dict) -> None:
                nonlocal response_status
                if message["type"] == "http.response.start":
                    response_status = int(message["status"])
                await send(message)

            try:
                await self.app(scope, receive, send_with_status)
            finally:
                route = scope.get("route")
                path = getattr(route, "path", None) or "unmatched"
                if path != "/metrics":
                    _MET_LAT.labels(scope["method"], path).observe(
                        time.perf_counter() - started
                    )
                    _MET_REQS.labels(
                        scope["method"], path, str(response_status)
                    ).inc()

    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus scrape endpoint (Wave 15). NOT exposed through the public edge —
        the frontend proxies only /api, so this is reachable only inside the compose
        network / over the tailnet for centerdeep to scrape. See docs/OPERATIONS.md."""
        await _refresh_operational_metrics()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

API = "/api"
app.include_router(auth.router, prefix=API)
app.include_router(sso.router, prefix=API)

# Tolerant inclusion of the ROUTERS-agent modules: each must expose `router`.
for _name in ROUTER_MODULES:
    try:
        _mod = importlib.import_module(f".routers.{_name}", package=__package__)
    except ImportError:
        log.info("Router module %r not present yet — skipping.", _name)
        continue
    app.include_router(_mod.router, prefix=API)
    log.info("Included router module %r.", _name)


@app.get("/healthz")
@app.get("/api/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Unauthenticated liveness: the process can serve an HTTP response."""
    return {"ok": True, "status": "alive", "app": settings.app_name, "version": __version__}


@app.get("/readyz")
@app.get("/api/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Unauthenticated readiness with dependency and degraded-state detail."""
    from .kb import freshness

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    queue = None
    try:
        from .analysis.jobs import queue_health

        queue = await queue_health()
    except Exception:  # noqa: BLE001
        log.warning("analysis queue readiness check failed", exc_info=True)
    kb = await freshness.effective_freshness()
    try:
        from .release import release_snapshot

        release_state = release_snapshot(
            kb_verified_as_of=kb.get("kb_verified_as_of"), kb_status=kb["status"]
        )
        release_ok = release_state["manifest_valid"] is True
    except Exception:  # noqa: BLE001 - invalid/missing inventory blocks readiness.
        release_ok = False
    worker_ok = bool(queue and queue.get("workers_alive", 0) > 0)
    ready = (
        db_ok
        and release_ok
        and (worker_ok or not settings.analysis_worker_required)
    )
    code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=code,
        content={
            "ok": ready,
            "status": "ready" if ready else "not_ready",
            "degraded": kb["status"] != "current" or bool(
                queue and (queue["expired_leases"] or queue["unsynced_runs"])
            ),
            "app": settings.app_name,
            "version": __version__,
            "dependencies": {
                "database": "ok" if db_ok else "unavailable",
                "knowledge_base": kb["status"],
                "analysis_worker": "ok" if worker_ok else "unavailable",
                "analysis_queue": queue,
                "release_manifest": "ok" if release_ok else "invalid",
            },
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/meta", response_model=MetaOut)
async def meta() -> MetaOut:
    """App identity + the legal-lane disclaimer (no auth — the login page shows it).

    kb_stale is additive: last cached eCFR freshness result (never a live network
    call here); None until the first successful check of this process."""
    from .kb import freshness
    from .release import release_snapshot

    cached = await freshness.effective_freshness()
    release = release_snapshot(
        kb_verified_as_of=cached.get("kb_verified_as_of"), kb_status=cached["status"]
    )
    # Prefer absolute legal URLs when a public base is known (VA portal + email
    # footers); fall back to same-origin relative paths so any host still works.
    public = (settings.public_base or "").rstrip("/")
    legal_url = f"{public}/legal" if public else "/legal"
    legal_api_url = f"{public}/api/legal" if public else "/api/legal"
    return MetaOut(
        name=settings.app_name,
        version=__version__,
        disclaimer=DISCLAIMER,
        va_enabled=settings.va_enabled,
        billing_self_serve=settings.billing_self_serve,
        legal_url=legal_url,
        legal_api_url=legal_api_url,
        kb_stale=cached["stale"],
        kb_verified_as_of=cached["kb_verified_as_of"],
        kb_status=cached["status"],
        release_id=release["release_id"],
        rule_version=release["rules"]["version"],
        rule_content_sha256=release["rules"]["content_sha256"],
    )


@app.get("/api/release", response_model=ReleaseOut)
async def release() -> ReleaseOut:
    """Public, privacy-safe build/rules/KB identity for support and release gates."""
    from .kb import freshness
    from .release import release_snapshot

    kb = await freshness.effective_freshness()
    return ReleaseOut.model_validate(
        release_snapshot(
            kb_verified_as_of=kb.get("kb_verified_as_of"), kb_status=kb["status"]
        )
    )


@app.get("/api/legal", response_model=LegalOut)
async def legal() -> LegalOut:
    """Plain-language terms of use + privacy policy (markdown; no auth — shown
    pre-signup, and a VA Lighthouse production-access prerequisite)."""
    from .va.legal import PRIVACY_MD, TERMS_MD

    return LegalOut(terms=TERMS_MD, privacy=PRIVACY_MD)


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "disclaimer": DISCLAIMER,
    }

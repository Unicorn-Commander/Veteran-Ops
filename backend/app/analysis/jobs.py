"""Durable PostgreSQL lease lifecycle for comprehensive-analysis work."""

from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from sqlalchemy import func, or_, select, update

from ..config import settings
from ..db import SessionLocal, engine, session_for_user
from ..models import AnalysisJob, AnalysisRun, AnalysisWorker, KBRefreshSignal
from .comprehensive_run import seed_steps

QUEUED_STATUSES = ("queued", "retryable")
LEASED_STATUSES = ("leased", "running")
ACTIVE_STATUSES = (*QUEUED_STATUSES, *LEASED_STATUSES)
TERMINAL_STATUSES = ("completed", "failed", "cancelled")

tenant_session = asynccontextmanager(session_for_user)
global_sessionmaker = SessionLocal
job_engine = engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def idempotency_digest(user_id: str, workspace_id: str, supplied: str | None) -> str:
    raw = (supplied or "").strip()
    if len(raw) > 200:
        raise ValueError("Idempotency-Key must be 200 characters or fewer.")
    if not raw:
        raw = str(uuid.uuid4())
    return hashlib.sha256(f"{user_id}:{workspace_id}:{raw}".encode()).hexdigest()


def backoff_seconds(attempts: int) -> int:
    exponent = max(0, int(attempts) - 1)
    return min(
        max(1, settings.analysis_job_backoff_seconds) * (2**exponent),
        max(1, settings.analysis_job_backoff_max_seconds),
    )


@dataclass(frozen=True)
class JobLease:
    job_id: str
    run_id: str
    user_id: str
    workspace_id: str
    worker_id: str
    lease_token: str
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class LeaseState:
    owned: bool
    cancel_requested: bool = False


@dataclass(frozen=True)
class Recovery:
    run_id: str
    user_id: str
    workspace_id: str
    status: str
    error: str | None
    available_at: datetime | None
    attempts: int
    max_attempts: int


def _lease(job: AnalysisJob) -> JobLease:
    return JobLease(
        job_id=str(job.id),
        run_id=str(job.run_id),
        user_id=str(job.user_id),
        workspace_id=str(job.workspace_id),
        worker_id=str(job.lease_owner),
        lease_token=str(job.lease_token),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
    )


async def claim_next_job(
    db,
    worker_id: str,
    *,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> JobLease | None:
    """Atomically lease one due job. PostgreSQL SKIP LOCKED enables many workers."""
    now = now or utcnow()
    lease_seconds = lease_seconds or settings.analysis_job_lease_seconds
    token = uuid.uuid4()
    due = or_(
        (
            AnalysisJob.status.in_(QUEUED_STATUSES)
            & (AnalysisJob.available_at <= now)
        ),
        (
            AnalysisJob.status.in_(LEASED_STATUSES)
            & (AnalysisJob.lease_expires_at.is_not(None))
            & (AnalysisJob.lease_expires_at <= now)
        ),
    )
    candidate = (
        select(AnalysisJob.id)
        .where(
            due,
            AnalysisJob.cancel_requested_at.is_(None),
            AnalysisJob.attempts < AnalysisJob.max_attempts,
        )
        .order_by(AnalysisJob.available_at, AnalysisJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    row = (
        await db.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == candidate)
            .values(
                status="leased",
                lease_owner=worker_id,
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=max(1, lease_seconds)),
                heartbeat_at=now,
                run_synced_at=None,
                updated_at=now,
            )
            .returning(AnalysisJob)
        )
    ).scalar_one_or_none()
    return _lease(row) if row is not None else None


async def claim_one(worker_id: str) -> JobLease | None:
    async with global_sessionmaker() as db:
        lease = await claim_next_job(db, worker_id)
        await db.commit()
        return lease


async def mark_running(lease: JobLease) -> JobLease | None:
    """Fence the leased attempt and mirror it into the tenant's RLS run row."""
    now = utcnow()
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.run_id == uuid.UUID(lease.run_id),
                    AnalysisJob.user_id == uuid.UUID(lease.user_id),
                    AnalysisJob.workspace_id == uuid.UUID(lease.workspace_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "leased",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None or job.cancel_requested_at is not None:
            return None
        job.status = "running"
        job.attempts += 1
        job.heartbeat_at = now
        job.run_synced_at = now
        run.status = "running"
        run.attempt_count = job.attempts
        run.max_attempts = job.max_attempts
        run.started_at = run.started_at or now
        run.finished_at = None
        run.next_attempt_at = None
        run.lease_expires_at = job.lease_expires_at
        run.error = None
        # Every retry restarts the whole deterministic pipeline. Resetting on the
        # first attempt too also cleans partial progress on a migrated legacy run.
        run.steps = seed_steps()
        await db.flush()
        return _lease(job)


async def renew_lease(lease: JobLease) -> LeaseState:
    now = utcnow()
    expires = now + timedelta(seconds=max(1, settings.analysis_job_lease_seconds))
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "running",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return LeaseState(owned=False)
        job.heartbeat_at = now
        job.lease_expires_at = expires
        job.run_synced_at = now
        run.lease_expires_at = expires
        return LeaseState(owned=True, cancel_requested=job.cancel_requested_at is not None)


async def defer_for_stale_kb(lease: JobLease) -> str:
    now = utcnow()
    available = now + timedelta(seconds=max(1, settings.analysis_job_stale_kb_retry_seconds))
    message = "Rating criteria are stale; analysis is paused until the curated KB is current."
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "leased",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return "lost"
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.cancelled_at = now
            job.last_error = "Analysis cancelled at your request."
            run.status = "cancelled"
            run.error = job.last_error
            run.finished_at = now
            run.next_attempt_at = None
            status = "cancelled"
        else:
            job.status = "retryable"
            job.available_at = available
            job.last_error = message
            run.status = "retryable"
            run.error = message
            run.next_attempt_at = available
            status = "retryable"
        _clear_lease(job)
        job.run_synced_at = now
        run.lease_expires_at = None
        return status


async def release_unstarted(lease: JobLease, error: str, *, delay_seconds: int = 1) -> str:
    """Return a fenced lease to the queue without consuming an attempt."""
    now = utcnow()
    available = now + timedelta(seconds=max(1, delay_seconds))
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "leased",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return "lost"
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.cancelled_at = now
            job.last_error = "Analysis cancelled at your request."
            run.status = "cancelled"
            run.error = job.last_error
            run.finished_at = now
            run.next_attempt_at = None
            status = "cancelled"
        else:
            job.status = "retryable"
            job.available_at = available
            job.last_error = error[:500]
            run.status = "retryable"
            run.error = error[:500]
            run.next_attempt_at = available
            status = "retryable"
        _clear_lease(job)
        job.run_synced_at = now
        run.lease_expires_at = None
        return status


def _clear_lease(job: AnalysisJob) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None


async def finish_success(lease: JobLease, result: dict) -> str:
    now = utcnow()
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "running",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return "lost"
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.cancelled_at = now
            job.last_error = "Analysis cancelled at your request."
            _clear_lease(job)
            job.run_synced_at = now
            run.status = "cancelled"
            run.error = job.last_error
            run.finished_at = now
            run.total_seconds = float(result["total_seconds"])
            run.next_attempt_at = None
            run.lease_expires_at = None
            return "cancelled"
        job.status = "completed"
        job.last_error = None
        _clear_lease(job)
        job.run_synced_at = now
        run.status = "completed"
        run.ran = dict(result["ran"])
        run.summary = dict(result["summary"])
        run.error = None
        run.finished_at = now
        run.total_seconds = float(result["total_seconds"])
        run.next_attempt_at = None
        run.lease_expires_at = None
        return "completed"


async def retry_or_fail(lease: JobLease, error: str, total_seconds: float) -> str:
    now = utcnow()
    message = (error or "analysis failed")[:500]
    operational_message = "Analysis attempt failed before completion."
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "running",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return "lost"
        if job.cancel_requested_at is not None:
            status = "cancelled"
            job.cancelled_at = now
            run.finished_at = now
        elif job.attempts >= job.max_attempts:
            status = "failed"
            run.finished_at = now
        else:
            status = "retryable"
            available = now + timedelta(seconds=backoff_seconds(job.attempts))
            job.available_at = available
            run.next_attempt_at = available
            run.finished_at = None
        job.status = status
        # The global dispatch table is deliberately PII-free. An arbitrary
        # exception can contain a filename or record excerpt, so only the RLS run
        # receives it; queue diagnostics retain a fixed operational classification.
        job.last_error = (
            "Analysis cancelled at the user's request."
            if status == "cancelled"
            else operational_message
        )
        _clear_lease(job)
        job.run_synced_at = now
        run.status = status
        run.error = message
        run.total_seconds = total_seconds
        run.lease_expires_at = None
        return status


async def cancel_owned(lease: JobLease, total_seconds: float = 0.0) -> None:
    await retry_or_fail(
        lease, "Analysis cancelled at your request.", total_seconds
    )


async def release_interrupted(lease: JobLease, total_seconds: float) -> str:
    """Requeue a running attempt stopped by a graceful worker shutdown.

    Operator restarts must not exhaust a veteran's bounded failure budget. The next
    worker reruns from the beginning under a fresh lease and advisory lock.
    """
    now = utcnow()
    message = "The analysis worker restarted; your review will resume automatically."
    async with tenant_session(lease.user_id, lease.workspace_id) as db:
        job = (
            await db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.id == uuid.UUID(lease.job_id),
                    AnalysisJob.lease_token == uuid.UUID(lease.lease_token),
                    AnalysisJob.lease_owner == lease.worker_id,
                    AnalysisJob.status == "running",
                ).with_for_update()
            )
        ).scalar_one_or_none()
        run = await db.get(AnalysisRun, uuid.UUID(lease.run_id))
        if job is None or run is None:
            return "lost"
        if job.cancel_requested_at is not None:
            status = "cancelled"
            job.cancelled_at = now
            run.finished_at = now
            message = "Analysis cancelled at your request."
        else:
            status = "retryable"
            job.attempts = max(0, job.attempts - 1)
            job.available_at = now + timedelta(seconds=1)
            run.finished_at = None
            run.next_attempt_at = job.available_at
        job.status = status
        job.last_error = message
        _clear_lease(job)
        job.run_synced_at = now
        run.status = status
        run.error = message
        run.attempt_count = job.attempts
        run.total_seconds = total_seconds
        run.lease_expires_at = None
        return status


async def recover_expired_jobs(db, *, now: datetime | None = None) -> list[Recovery]:
    """Recover abandoned leases and queued cancellations after a worker restart."""
    now = now or utcnow()
    rows = (
        await db.execute(
            select(AnalysisJob)
            .where(
                ~AnalysisJob.status.in_(TERMINAL_STATUSES),
                or_(
                    AnalysisJob.cancel_requested_at.is_not(None),
                    (
                        AnalysisJob.status.in_(QUEUED_STATUSES)
                        & (AnalysisJob.attempts >= AnalysisJob.max_attempts)
                    ),
                    (
                        AnalysisJob.status.in_(LEASED_STATUSES)
                        & AnalysisJob.lease_expires_at.is_not(None)
                        & (AnalysisJob.lease_expires_at <= now)
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    recovered: list[Recovery] = []
    for job in rows:
        if job.cancel_requested_at is not None:
            status = "cancelled"
            error = "Analysis cancelled at your request."
            available = None
            job.cancelled_at = now
        elif job.attempts >= job.max_attempts:
            status = "failed"
            error = (
                "Worker lease expired after the maximum number of attempts."
                if job.status in LEASED_STATUSES
                else "Analysis reached the maximum number of attempts."
            )
            available = None
        else:
            status = "retryable"
            error = "Worker lease expired; the analysis will resume from durable state."
            available = now + timedelta(seconds=backoff_seconds(job.attempts))
            job.available_at = available
        job.status = status
        job.last_error = error
        _clear_lease(job)
        # Recovery discovers work without a tenant GUC. Mark the FORCE-RLS result
        # as unsynchronized before committing so reconciliation is crash-convergent.
        job.run_synced_at = None
        recovered.append(
            Recovery(
                run_id=str(job.run_id),
                user_id=str(job.user_id),
                workspace_id=str(job.workspace_id),
                status=status,
                error=error,
                available_at=available,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
            )
        )
    return recovered


async def recover_and_sync() -> int:
    async with global_sessionmaker() as db:
        await recover_expired_jobs(db)
        await db.commit()
    return await reconcile_unsynced_runs()


async def reconcile_unsynced_runs() -> int:
    """Repair every queue/run mismatch left by a crash between transactions.

    The unsynced marker is durable on the global metadata row. Each repair then
    updates the queue marker and tenant's FORCE-RLS run in one tenant transaction.
    Re-running this scan is idempotent, including after interruption mid-batch.
    """
    async with global_sessionmaker() as db:
        pending = (
            await db.execute(
                select(
                    AnalysisJob.id,
                    AnalysisJob.user_id,
                    AnalysisJob.workspace_id,
                )
                .where(AnalysisJob.run_synced_at.is_(None))
                .order_by(AnalysisJob.updated_at, AnalysisJob.created_at)
                .limit(500)
            )
        ).all()
    repaired = 0
    for job_id, user_id, workspace_id in pending:
        async with tenant_session(str(user_id), str(workspace_id)) as db:
            job = (
                await db.execute(
                    select(AnalysisJob)
                    .where(
                        AnalysisJob.id == job_id,
                        AnalysisJob.run_synced_at.is_(None),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if job is None:
                continue
            run = await db.get(AnalysisRun, job.run_id)
            if run is None:
                # ON DELETE CASCADE normally makes this impossible; leave the
                # marker outstanding so an operator can diagnose corruption.
                continue
            if not (job.status == "completed" and run.status == "complete"):
                run.status = job.status
            run.error = job.last_error
            run.attempt_count = job.attempts
            run.max_attempts = job.max_attempts
            run.cancel_requested_at = job.cancel_requested_at
            run.next_attempt_at = job.available_at if job.status == "retryable" else None
            run.lease_expires_at = (
                job.lease_expires_at if job.status in LEASED_STATUSES else None
            )
            if job.status in ("failed", "cancelled"):
                run.finished_at = run.finished_at or job.updated_at or utcnow()
            elif job.status in ACTIVE_STATUSES:
                run.finished_at = None
            job.run_synced_at = utcnow()
            repaired += 1
    return repaired


async def worker_heartbeat(worker_id: str, status: str = "running") -> None:
    now = utcnow()
    async with global_sessionmaker() as db:
        row = await db.get(AnalysisWorker, worker_id)
        if row is None:
            db.add(
                AnalysisWorker(
                    worker_id=worker_id,
                    status=status,
                    started_at=now,
                    heartbeat_at=now,
                )
            )
        else:
            row.status = status
            row.heartbeat_at = now
        await db.commit()


async def queue_health() -> dict:
    """PII-free aggregate status for readiness and operator diagnostics."""
    now = utcnow()
    alive_after = now - timedelta(
        seconds=max(30, settings.analysis_job_heartbeat_seconds * 3)
    )
    async with global_sessionmaker() as db:
        grouped = (
            await db.execute(
                select(AnalysisJob.status, func.count(AnalysisJob.id)).group_by(
                    AnalysisJob.status
                )
            )
        ).all()
        alive = (
            await db.execute(
                select(func.count(AnalysisWorker.worker_id)).where(
                    AnalysisWorker.status == "running",
                    AnalysisWorker.heartbeat_at >= alive_after,
                )
            )
        ).scalar_one()
        stale_workers = (
            await db.execute(
                select(func.count(AnalysisWorker.worker_id)).where(
                    AnalysisWorker.status == "running",
                    AnalysisWorker.heartbeat_at < alive_after,
                )
            )
        ).scalar_one()
        expired = (
            await db.execute(
                select(func.count(AnalysisJob.id)).where(
                    AnalysisJob.status.in_(LEASED_STATUSES),
                    AnalysisJob.lease_expires_at < now,
                )
            )
        ).scalar_one()
        unsynced = (
            await db.execute(
                select(func.count(AnalysisJob.id)).where(
                    AnalysisJob.run_synced_at.is_(None)
                )
            )
        ).scalar_one()
        oldest_active = (
            await db.execute(
                select(func.min(AnalysisJob.created_at)).where(
                    AnalysisJob.status.in_(ACTIVE_STATUSES)
                )
            )
        ).scalar_one_or_none()
        failed_recent = (
            await db.execute(
                select(func.count(AnalysisJob.id)).where(
                    AnalysisJob.status == "failed",
                    AnalysisJob.updated_at >= now - timedelta(hours=1),
                )
            )
        ).scalar_one()
        retried_jobs = (
            await db.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.attempts > 1)
            )
        ).scalar_one()
    counts = Counter({status: count for status, count in grouped})
    if oldest_active is not None and oldest_active.tzinfo is None:
        oldest_active = oldest_active.replace(tzinfo=timezone.utc)
    oldest_seconds = (
        max(0.0, (now - oldest_active).total_seconds())
        if oldest_active is not None
        else 0.0
    )
    return {
        "workers_alive": int(alive or 0),
        "workers_stale": int(stale_workers or 0),
        "queued": int(counts["queued"] + counts["retryable"]),
        "running": int(counts["leased"] + counts["running"]),
        "retryable": int(counts["retryable"]),
        "expired_leases": int(expired or 0),
        "unsynced_runs": int(unsynced or 0),
        "failed": int(counts["failed"]),
        "failed_recent": int(failed_recent or 0),
        "retried_jobs": int(retried_jobs or 0),
        "oldest_active_seconds": round(oldest_seconds, 3),
        "status_counts": {
            status: int(counts[status])
            for status in (*ACTIVE_STATUSES, *TERMINAL_STATUSES)
        },
    }


async def durable_kb_stale() -> bool:
    """Cross-process stale gate backed by the persisted refresh-needed signal."""
    async with global_sessionmaker() as db:
        count = (
            await db.execute(
                select(func.count(KBRefreshSignal.id)).where(
                    KBRefreshSignal.status == "open",
                    KBRefreshSignal.detected_source_date.is_not(None),
                    KBRefreshSignal.detected_source_date > KBRefreshSignal.kb_verified_as_of,
                )
            )
        ).scalar_one()
    return bool(count)


@asynccontextmanager
async def advisory_run_lock(run_id: str):
    """Postgres session lock closes the rare lease-expiry/old-worker overlap window."""
    async with job_engine.connect() as conn:
        if conn.dialect.name != "postgresql":
            yield True
            return
        key = int.from_bytes(uuid.UUID(run_id).bytes[:8], byteorder="big", signed=True)
        locked = bool(
            (await conn.execute(select(func.pg_try_advisory_lock(key)))).scalar_one()
        )
        try:
            yield locked
        finally:
            if locked:
                await conn.execute(select(func.pg_advisory_unlock(key)))

"""Standalone or embedded durable comprehensive-analysis worker."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time
import uuid

from ..config import settings
from ..kb import freshness
from . import comprehensive_run
from .jobs import (
    JobLease,
    advisory_run_lock,
    cancel_owned,
    claim_one,
    defer_for_stale_kb,
    durable_kb_stale,
    finish_success,
    mark_running,
    recover_and_sync,
    release_interrupted,
    release_unstarted,
    renew_lease,
    retry_or_fail,
    worker_heartbeat,
)

log = logging.getLogger("veteran_ops.analysis.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{str(uuid.uuid4())[:8]}"


async def _lease_monitor(
    lease: JobLease,
    worker_id: str,
    stop_event: asyncio.Event | None = None,
) -> str:
    interval = max(
        1.0,
        min(
            float(settings.analysis_job_heartbeat_seconds),
            max(1.0, float(settings.analysis_job_lease_seconds) / 3),
        ),
    )
    while True:
        if stop_event is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass
            if stop_event.is_set():
                return "shutdown"
        try:
            await worker_heartbeat(worker_id)
            state = await renew_lease(lease)
        except Exception as exc:  # noqa: BLE001 - stop work if fencing cannot be proven.
            log.warning(
                "analysis lease monitor failed (run=%s error_type=%s)",
                lease.run_id,
                type(exc).__name__,
            )
            return "lost"
        if not state.owned:
            return "lost"
        if state.cancel_requested:
            return "cancelled"


async def process_lease(
    lease: JobLease,
    worker_id: str,
    *,
    stop_event: asyncio.Event | None = None,
) -> str:
    """Execute one fenced lease, including stale-KB and cancellation gates."""
    async with advisory_run_lock(lease.run_id) as locked:
        if not locked:
            return await release_unstarted(
                lease,
                "Another worker still holds this analysis run; retrying shortly.",
                delay_seconds=max(1, settings.analysis_job_heartbeat_seconds),
            )

        cached_stale = freshness.cached_effective_freshness().get("stale") is True
        if cached_stale or await durable_kb_stale():
            return await defer_for_stale_kb(lease)

        active = await mark_running(lease)
        if active is None:
            return "lost"

        started = time.monotonic()
        pipeline = asyncio.create_task(
            comprehensive_run.run_comprehensive_job(
                active.run_id,
                active.user_id,
                active.workspace_id,
            )
        )
        monitor = asyncio.create_task(_lease_monitor(active, worker_id, stop_event))
        try:
            done, _ = await asyncio.wait(
                {pipeline, monitor}, return_when=asyncio.FIRST_COMPLETED
            )

            if monitor in done:
                reason = await monitor
                pipeline.cancel()
                # Both tasks can finish in the same loop turn. Consume any pipeline
                # exception here so cancellation/lease loss remains the authoritative
                # durable transition instead of escaping the worker cycle.
                await asyncio.gather(pipeline, return_exceptions=True)
                if reason == "cancelled":
                    await cancel_owned(
                        active, round(time.monotonic() - started, 2)
                    )
                    return "cancelled"
                if reason == "shutdown":
                    return await release_interrupted(
                        active, round(time.monotonic() - started, 2)
                    )
                return "lost"

            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            total = round(time.monotonic() - started, 2)
            if pipeline.cancelled():
                return await retry_or_fail(
                    active, "Analysis pipeline stopped unexpectedly.", total
                )
            try:
                result = pipeline.result()
            except Exception as exc:  # noqa: BLE001 - durable retry policy owns the failure.
                status = await retry_or_fail(active, str(exc), total)
                log.warning(
                    "analysis attempt failed (run=%s attempt=%s status=%s error_type=%s)",
                    active.run_id,
                    active.attempts,
                    status,
                    type(exc).__name__,
                )
                return status
            return await finish_success(active, result)
        except asyncio.CancelledError:
            pipeline.cancel()
            monitor.cancel()
            await asyncio.gather(pipeline, monitor, return_exceptions=True)
            try:
                await release_interrupted(active, round(time.monotonic() - started, 2))
            except Exception as exc:  # noqa: BLE001 - lease expiry remains the fallback.
                log.warning(
                    "analysis shutdown release failed (run=%s error_type=%s)",
                    active.run_id,
                    type(exc).__name__,
                )
            raise
        finally:
            for task in (pipeline, monitor):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pipeline, monitor, return_exceptions=True)


async def run_worker_loop(
    *,
    stop_event: asyncio.Event | None = None,
    worker_id: str | None = None,
) -> None:
    stop = stop_event or asyncio.Event()
    worker_id = worker_id or default_worker_id()
    log.info("durable analysis worker started (%s)", worker_id)
    try:
        while not stop.is_set():
            try:
                await worker_heartbeat(worker_id)
                recovered = await recover_and_sync()
                if recovered:
                    log.warning(
                        "recovered %s abandoned/cancelled analysis job(s)", recovered
                    )
                lease = await claim_one(worker_id)
                if lease is not None:
                    await process_lease(lease, worker_id, stop_event=stop)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - retry transient infrastructure faults.
                log.error(
                    "analysis worker cycle failed (worker=%s error_type=%s error=%s)",
                    worker_id,
                    type(exc).__name__,
                    str(exc)[:300],
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=max(0.1, settings.analysis_worker_poll_seconds)
                )
            except TimeoutError:
                pass
    finally:
        try:
            await worker_heartbeat(worker_id, "stopped")
        except Exception as exc:  # noqa: BLE001 - shutdown must remain best effort.
            log.warning(
                "analysis worker stop heartbeat failed (worker=%s error_type=%s)",
                worker_id,
                type(exc).__name__,
            )
        log.info("durable analysis worker stopped (%s)", worker_id)


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows event loop.
            pass
    await run_worker_loop(stop_event=stop)


if __name__ == "__main__":
    # Standalone process — configure root logging so cycle failures are visible
    # in `docker logs` without relying on the API app's logging setup.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main())

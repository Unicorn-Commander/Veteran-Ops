from __future__ import annotations

import asyncio

from app.config import settings
from app.firm import jobs
from app.intake import process as intake
from app.routers.strategy import _active_finding_keys


def test_intake_batch_coalesces_ready_documents_to_one_sweep(monkeypatch):
    processed: list[str] = []
    triggered: list[tuple[str, str | None]] = []

    async def _safe(user_id, document_id, workspace_id=None, *, trigger_deep_dive=True):
        assert trigger_deep_dive is False
        processed.append(document_id)

    async def _ready(user_id, document_ids, workspace_id=None):
        return True

    async def _trigger(user_id, workspace_id=None):
        triggered.append((user_id, workspace_id))

    monkeypatch.setattr(intake, "process_document_safe", _safe)
    monkeypatch.setattr(intake, "_any_documents_ready", _ready)
    monkeypatch.setattr(intake, "_trigger_intake_deep_dive", _trigger)

    asyncio.run(intake.process_documents_batch("user-1", ["doc-1", "doc-2"], "ws-1"))
    assert processed == ["doc-1", "doc-2"]
    assert triggered == [("user-1", "ws-1")]


def test_schedule_flag_defaults_to_no_sweep(monkeypatch):
    called = False

    async def _sweep(**_kwargs):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(settings, "deep_dive_on_schedule", False)
    monkeypatch.setattr(jobs, "sweep_users", _sweep)
    asyncio.run(jobs.run_periodic_sweeps(interval_hours=1))
    assert called is False


def test_notification_comparison_ignores_inactive_conflict_losers():
    payload = {
        "findings": [
            {"key": "active", "active": True},
            {"key": "superseded", "active": False},
            {"key": "legacy-without-annotation"},
        ]
    }
    assert _active_finding_keys(payload) == {"active", "legacy-without-annotation"}

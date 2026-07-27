"""Rating Raider — the conversational CWO agent (SSE streaming chat).

POST /raider/chat streams the agent's turn as Server-Sent Events: tool-run markers
and answer tokens, so the veteran watches it think and act. The stream opens its OWN
RLS-scoped session (the request's Depends session is torn down before the streaming
generator runs — the same reason background tasks re-establish RLS), builds the
veteran's dossier once, and drives the agent loop.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from ..config import settings
from ..deps import current_user_id, current_workspace_id
from ..raider.agent import MAX_HISTORY_MESSAGES, bound_history, run_agent
from ..raider.tools import ToolCtx

log = logging.getLogger("veteran_ops.raider")
router = APIRouter(prefix="/raider", tags=["raider"])


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


@router.get("/status")
async def raider_status(uid: str = Depends(current_user_id)) -> dict:
    """Is the agent available? (the gateway must be configured.)"""
    return {"available": bool(settings.llm_base_url)}


@router.get("/interview-seed")
async def raider_interview_seed(
    uid: str = Depends(current_user_id),
    mode: str = "post_analysis",
) -> dict:
    """Deterministic post-analysis interview seed (opening + gap questions).

    No LLM. Used by /raider?mode=post_analysis to start a coach interview.
    """
    from ..db import session_for_user
    from ..firm.context import build_dossier, plan_decision_status_updates
    from ..strategy.coach import enrich_plan_with_coach
    from ..strategy.plan import build_game_plan
    from contextlib import asynccontextmanager

    async with asynccontextmanager(session_for_user)(uid) as db:
        dossier = await build_dossier(db, uid)
        plan = build_game_plan(
            conditions=dossier.conditions,
            denials=dossier.denials,
            suggestions=dossier.suggestions,
            active_itf=dossier.active_itf,
            current_combined=dossier.current_combined,
            generated_at=dossier.generated_at,
        )
        enrich_plan_with_coach(
            plan,
            conditions=dossier.conditions,
            denials=dossier.denials,
            decision_status_pending=0,
        )
        interview = (plan.get("coach") or {}).get("interview") or {}
        interview["mode"] = mode or "post_analysis"
        return interview


@router.post("/chat")
async def raider_chat(
    payload: ChatIn,
    request: Request,
    uid: str = Depends(current_user_id),
    wsid: str | None = Depends(current_workspace_id),
) -> StreamingResponse:
    """Stream one assistant turn as SSE. The client sends the running conversation;
    the agent grounds on the veteran's own record + 38 CFR and streams its reply."""
    if not settings.llm_base_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant is not configured.")
    # Char + message budget (token guard). Dossier carries durable case context;
    # chat history is only the short conversational window.
    history = bound_history(
        [m.model_dump() for m in payload.messages],
        max_messages=MAX_HISTORY_MESSAGES,
    )
    host = request.headers.get("host")  # for per-deployment links (e.g. Center Deep)

    async def event_stream():
        # Own RLS session — the request Depends session is gone once we start streaming.
        from ..db import session_for_user
        from ..firm.context import build_dossier

        try:
            async with asynccontextmanager(session_for_user)(uid, wsid) as db:
                from ..overrides import workspace_privacy_mode
                dossier = await build_dossier(db, uid)
                pm = await workspace_privacy_mode(db)  # per-workspace privacy choice
                ctx = ToolCtx(db=db, uid=uid, dossier=dossier, host=host, privacy_mode=pm)
                async for event in run_agent(ctx, history):
                    yield _sse(event)
        except Exception:  # noqa: BLE001 — never break the SSE stream with a 500
            log.warning("raider chat stream failed", exc_info=True)
            yield _sse({"type": "token", "text": "I couldn't start just now — please try again."})
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

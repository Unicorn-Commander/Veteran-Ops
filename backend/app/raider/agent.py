"""The CWO agent loop — Rating Raider's brain.

Given the conversation + the veteran's dossier, it runs a bounded tool-calling loop:
reason → call grounded tools → reason over the results → answer. The final answer is
STREAMED. Two model tiers: tool orchestration + the closing answer reason over
findings + public CFR (the `reasoning` tier, which may be a larger model); anything
that ingests the veteran's own record text stays on the local model (the PII guard
in overrides.effective_model_for). Every streamed answer is legal-lane checked.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator

from ..config import settings
from ..overrides import effective_model_for
from ..llm.gateway import gateway
from ..strategy.briefing import _LANE_BLOCK
from .tools import ToolCtx, openai_tool_specs, run_tool, tool_touches_pii

log = logging.getLogger("veteran_ops.raider.agent")

MAX_TOOL_ROUNDS = 6

# Token-budget guard for chat history. Message *count* alone is not enough —
# a few multi-thousand-character turns still blow local-context windows.
# Rough heuristic: ~4 chars ≈ 1 token for English; 28k chars ≈ 7k tokens of
# conversation, leaving room for system prompt + tool payloads + answer.
MAX_HISTORY_MESSAGES = 24
MAX_HISTORY_CHARS = 28_000
MAX_MESSAGE_CHARS = 4_000
# Tool results already hard-capped when appended; keep that aligned.
MAX_TOOL_RESULT_CHARS = 6_000


def bound_history(
    history: list[dict],
    *,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_HISTORY_CHARS,
    max_message_chars: int = MAX_MESSAGE_CHARS,
) -> list[dict]:
    """Return a conversation window that fits a char budget.

    Always keeps the most recent message (the current user turn). Older turns
    are dropped from the front until the remaining content fits. Individual
    messages are truncated at the tail when over max_message_chars. Pure and
    side-effect free — safe to unit-test without a model.
    """
    if not history:
        return []
    cleaned: list[dict] = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role not in ("user", "assistant", "system", "tool"):
            continue
        content = str(m.get("content") or "")
        if len(content) > max_message_chars:
            content = content[: max_message_chars - 1].rstrip() + "…"
        out = {"role": role, "content": content}
        # Preserve tool-call metadata if present (not used for budget, but keep shape).
        if "tool_calls" in m:
            out["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            out["tool_call_id"] = m["tool_call_id"]
        if "name" in m:
            out["name"] = m["name"]
        cleaned.append(out)

    if len(cleaned) > max_messages:
        cleaned = cleaned[-max_messages:]

    # Walk from the end so the current turn is never dropped.
    total = 0
    kept_rev: list[dict] = []
    for m in reversed(cleaned):
        n = len(m.get("content") or "")
        if kept_rev and total + n > max_chars:
            break
        kept_rev.append(m)
        total += n
    kept = list(reversed(kept_rev))
    # Safety: if even the last message alone exceeds the budget, keep a truncated it.
    if not kept and cleaned:
        last = dict(cleaned[-1])
        body = last.get("content") or ""
        last["content"] = body[: max(0, max_chars - 1)].rstrip() + ("…" if body else "")
        kept = [last]
    return kept


# Local models sometimes emit a tool call as literal text (Qwen's <tool_call>… /
# <function=…> forms) instead of a proper tool_calls field — strip any that leak into
# a final answer so the veteran never sees raw call syntax.
_TOOL_SYNTAX = re.compile(
    r"<tool_call>.*?</tool_call>|<function=.*?</function>|<parameter=.*?(?:</parameter>|$)",
    re.DOTALL | re.IGNORECASE,
)
_FINALIZE = (
    "You now have everything you need. Write your answer to the veteran in plain, warm "
    "language — do NOT call any more tools. Lead with the direct answer, cite the "
    "specific conditions/criteria/forms, and end with the concrete next step."
)


def _clean_answer(text: str) -> str:
    return _TOOL_SYNTAX.sub("", text or "").strip()

SYSTEM_PROMPT = (
    "You are Rating Raider — a Chief Warrant Officer who is the veteran's own claims "
    "expert inside this app. You are warm, plain-spoken, and relentless on their "
    "behalf: you do the work a good VSO or claims firm would, but the veteran always "
    "drives.\n\n"
    "HOW YOU WORK:\n"
    "- Ground everything in THIS veteran's record and the ACTUAL 38 CFR. Call "
    "get_my_situation before advising, use search_va_rulebook to quote real criteria, "
    "and run the analysis tools rather than guessing. Never invent a diagnostic code, "
    "a percentage, or an eligibility — if a tool didn't return it, don't assert it.\n"
    "- Be proactive: surface the angles a veteran wouldn't know to ask for (secondary "
    "conditions, TDIU, deadlines they're about to miss, a rating that looks low).\n"
    "- Explain in plain language first, then the reg/form. Short paragraphs.\n\n"
    "THE LINE YOU NEVER CROSS (you are software, not an accredited representative):\n"
    "- You ORGANIZE, EXPLAIN, PREPARE, and give grounded analysis. You never file, "
    "submit, or represent the veteran before VA, and you never ask for their VA.gov "
    "login.\n"
    "- You never diagnose a new medical condition and never write a formal medical "
    "nexus letter (that is a provider's job). You MAY give cited analysis of what the "
    "record and 38 CFR show — e.g. criteria for a rating percentage, that a condition "
    "appears service-connected on the evidence, or 'at least as likely as not' as an "
    "educational framing of the VA standard — as long as every number/code comes from "
    "a tool result and you do NOT guarantee what VA will decide.\n"
    "- NEVER promise a VA outcome. Barred: 'you will be granted', 'you'll get 70%', "
    "'guarantee', '100% chance', 'you will receive [a rating/award]'. Allowed: "
    "'the criteria for 70% require…', 'your record shows…', 'this meets the "
    "criteria for…', 'worth reviewing with a free VSO'. VA makes every decision.\n"
    "- When a claim needs filing or representation, point them to free VA-accredited "
    "help (a VSO); never a paid claim company.\n"
    "- SSN and signatures are always theirs to complete by hand.\n\n"
    "Close with the concrete next step and, when useful, the exact form or workflow."
)


_LANE_FALLBACK = (
    "Here's the honest version: I can organize your record and show you exactly what "
    "the VA's criteria require and what your file already shows — but I can't predict "
    "VA's decision or promise a rating. Want me to lay out the criteria against your "
    "evidence, or set you up with a free accredited VSO to file?"
)

_REVISE_SYSTEM = (
    "You rewrite a veteran-facing answer to strip ONLY guaranteed VA outcomes "
    "('you will be granted', 'you'll get 70%', 'guarantee', '100% chance', "
    "'you will receive a rating') while keeping ALL substance, grounded analysis, "
    "specifics, and warmth. Cited opinions may stay: criteria language, what the "
    "record shows, educational 'at least as likely as not' framing of the VA "
    "standard, and service-connection analysis grounded in tools. Replace bare "
    "promises with 'the criteria for X require…', 'your record shows…', 'worth "
    "reviewing with a free VSO'. Keep every fact, code, %, form, and next step. "
    "Return only the rewritten answer."
)


def _lane_ok(text: str) -> bool:
    return not (text and _LANE_BLOCK.search(text))


_PCT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b)", re.IGNORECASE)
_DC_RE = re.compile(r"\bDC\s*(\d{4})\b|\b([5-9]\d{3})\b", re.IGNORECASE)
_DOLLAR_RE = re.compile(r"\$\s?([\d,]+)")
_ANY_NUM_RE = re.compile(r"\d[\d,]*")


def _digits(s: str) -> str:
    """Normalize a number token for comparison: drop commas and leading zeros."""
    return (s or "").replace(",", "").lstrip("0") or "0"


def _answer_grounded(answer: str, messages: list[dict]) -> bool:
    """Conservative anti-fabrication for the closing answer (its equivalent of the
    firm path's grounding validators): every percentage, dollar figure, and
    diagnostic code the answer STATES must trace to a number the model was given
    this turn — system prompt + history + tool results. Comparison is
    formatting-insensitive (a context value of 60 grounds an answer of "60%", and
    "$1,361.88" grounds "1,361"), and the context set is EVERY number available to
    the model, so this fires only on a number invented out of nothing — near-zero
    false positives, while catching a fabricated rating/dollar/DC before it streams."""
    ctx_nums = {_digits(n) for n in _ANY_NUM_RE.findall(
        " ".join(str(m.get("content") or "") for m in messages))}
    claimed = {_digits(m) for m in _PCT_RE.findall(answer)}
    claimed |= {_digits(m) for m in _DOLLAR_RE.findall(answer)}
    claimed |= {_digits(a or b) for a, b in _DC_RE.findall(answer)}
    return not (claimed - ctx_nums)


def _chunks(text: str, size: int = 3):
    """Yield the answer in small word-groups so the client renders a live-typing
    stream over an already-finished, already-safe answer."""
    words = (text or "").split(" ")
    for i in range(0, len(words), size):
        yield (" " if i else "") + " ".join(words[i : i + size])


async def _make_lane_safe(
    text: str, *, model: str,
    privacy_mode: bool | None = None, touches_pii: bool = False,
) -> str:
    """If the answer tripped the legal-lane gate, REVISE it (preserve the substance)
    rather than discard it. Only fall back to the generic redirect if even the
    revision can't come clean — so a veteran keeps the real, grounded help."""
    if _lane_ok(text):
        return text
    log.info("raider answer tripped the lane gate — revising")
    try:
        revised = await gateway.complete(
            [{"role": "system", "content": _REVISE_SYSTEM}, {"role": "user", "content": text}],
            model=model,
            temperature=0.1,
            max_tokens=1200,
            privacy_mode=privacy_mode,
            touches_pii=touches_pii,
        )
        if revised and _lane_ok(revised):
            return revised.strip()
    except Exception:  # noqa: BLE001
        log.warning("raider lane revision failed", exc_info=True)
    return _LANE_FALLBACK


async def run_agent(
    ctx: ToolCtx,
    history: list[dict],
) -> AsyncGenerator[dict, None]:
    """Drive one assistant turn. Yields event dicts:
      {"type":"tool", "name":..., "status":"start|done"}   — a tool ran
      {"type":"token", "text":...}                          — a piece of the answer
      {"type":"done"}                                       — turn complete
    `history` is the prior conversation as [{role, content}]. Never raises.
    History is char-budget bounded before the model sees it (token guard).
    """
    tools = openai_tool_specs()
    window = bound_history(history)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *window]
    # If any tool this turn read the veteran's record, the closing reasoning stays
    # local too (belt-and-suspenders over settings.model_for).
    touched_pii = False
    pm = getattr(ctx, "privacy_mode", None)  # per-workspace privacy choice (None → global)

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            model = effective_model_for(tier="reasoning", touches_pii=touched_pii, privacy_mode=pm)
            msg = await gateway.complete_with_tools(
                messages, tools, model=model,
                privacy_mode=pm, touches_pii=touched_pii,
            )
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                break  # model wants to answer — stream it below

            # Record the assistant's tool-call message, then run each tool.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                name = tc.function.name
                if tool_touches_pii(name):
                    touched_pii = True
                yield {"type": "tool", "name": name, "status": "start"}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                result = await run_tool(name, args, ctx)
                yield {"type": "tool", "name": name, "status": "done"}
                # A UI-control tool asks the app to act (e.g. navigate). Re-emit it as a
                # `ui` event the frontend performs; the model still sees the tool result.
                if isinstance(result, dict) and isinstance(result.get("ui_action"), dict):
                    yield {"type": "ui", "action": result["ui_action"]}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(result)[:MAX_TOOL_RESULT_CHARS],
                    }
                )

        # Final answer. We generate it, run the legal-lane check + (if needed) a
        # substance-preserving revision, THEN stream the safe text — so the veteran
        # never sees a promissory sentence flash and get yanked. The tool-run chips
        # already showed the agent working, so the brief compose pause reads as
        # deliberate, not laggy. touched_pii keeps a record-referencing answer local.
        model = effective_model_for(tier="reasoning", touches_pii=touched_pii, privacy_mode=pm)
        answer_messages = [*messages, {"role": "system", "content": _FINALIZE}]
        draft = _clean_answer(await gateway.complete(
            answer_messages, model=model, temperature=0.3, max_tokens=1200,
            privacy_mode=pm, touches_pii=touched_pii,
        ))
        if len(draft) < 20:
            # The model only tried to call more tools — force a plain answer once more.
            draft = _clean_answer(await gateway.complete(
                answer_messages, model=model, temperature=0.4, max_tokens=1200,
                privacy_mode=pm, touches_pii=touched_pii,
            ))
        answer = await _make_lane_safe(
            draft, model=effective_model_for(touches_pii=touched_pii, privacy_mode=pm),
            privacy_mode=pm, touches_pii=touched_pii,
        )
        if len(answer) < 20 or not _answer_grounded(answer, messages):
            answer = _LANE_FALLBACK
        # Stream the finished, safe answer in word chunks for the live-typing feel.
        for chunk in _chunks(answer):
            yield {"type": "token", "text": chunk}
    except Exception:  # noqa: BLE001 — the chat must degrade gracefully, never 500 mid-stream
        log.warning("raider agent loop failed", exc_info=True)
        yield {
            "type": "token",
            "text": "I hit a snag pulling that together. Try asking again, or open your Claim Plan to see the analysis directly.",
        }
    yield {"type": "done"}

"""The agent's tool belt — every capability wrapped as a grounded, RLS-scoped,
read-only, legal-lane tool the CWO agent can call.

Contract for every tool:
  * Read-only. Nothing here files, submits, mutates a claim, or writes the profile.
  * Grounded. Results come from the deterministic engines + the vendored/curated 38
    CFR corpus — never invented. The agent reasons over these; it never originates a
    diagnostic code, percentage, or eligibility on its own.
  * Compact. Each returns a small JSON-able dict the model can reason over cheaply.
  * touches_pii marks tools whose result contains the veteran's OWN record (so the
    agent loop keeps those turns on the local model).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..firm.context import VeteranDossier
from ..kb.store import retrieve_cards
from ..pdf.registry import REGISTRY, get_spec
from ..strategy.concurrent_pay import screen_concurrent_pay

log = logging.getLogger("veteran_ops.raider.tools")

# Tool handlers get the shared per-request context and the parsed args, and return a
# JSON-able dict. The dossier is assembled ONCE per chat turn and threaded in so
# tools don't each re-query the veteran's whole record.
Handler = Callable[["ToolCtx", dict], Awaitable[dict]]


@dataclass
class ToolCtx:
    db: AsyncSession
    uid: str
    dossier: VeteranDossier
    host: str | None = None  # the valor host the veteran is on (for per-deployment links)
    # Resolved per-workspace privacy choice (overrides.workspace_privacy_mode). None →
    # the global/env default. Threaded into the agent's model resolution so a
    # privacy-first workspace keeps its turn local even under quality-first defaults.
    privacy_mode: bool | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Handler
    touches_pii: bool = False


# ── Handlers ─────────────────────────────────────────────────────────────────────


async def _get_my_situation(ctx: ToolCtx, args: dict) -> dict:
    d = ctx.dossier
    conditions = [
        {
            "name": c.get("name"),
            "diagnostic_code": c.get("diagnostic_code"),
            "current_rating": c.get("current_rating"),
            "va_status": c.get("va_status"),
            "readiness_band": c.get("band"),
            "still_needed": c.get("missing") or [],
        }
        for c in (d.conditions or [])
    ]
    return {
        "current_combined_rating": d.current_combined,
        "conditions": conditions,
        "denied_or_shorted": [
            {"name": x.get("name"), "note": x.get("reason") or x.get("note")}
            for x in (d.denials or [])
        ],
        "active_intent_to_file": bool(d.active_itf),
        "dependents_on_file": len(getattr(d, "dependents", None) or []),
    }


async def _run_deep_dive(ctx: ToolCtx, args: dict) -> dict:
    # Lazy import: the firm pulls the LLM gateway, keep tool import light.
    from ..firm.orchestrator import deep_dive

    result = await deep_dive(ctx.db, ctx.dossier)
    payload = result.to_dict()
    # Trim to what the agent needs to reason + explain (drop heavy internals).
    findings = [
        {
            "title": f.get("title"),
            "kind": f.get("seed", {}).get("origin") or f.get("kind"),
            "severity": f.get("severity"),
            "active": f.get("seed", {}).get("active", True),
            "what_this_is": (f.get("body") or "")[:600],
            "needs": f.get("needs") or [],
            "regs": f.get("regs") or [],
        }
        for f in payload.get("findings", [])
    ]
    return {
        "candidates_considered": payload.get("candidates_considered"),
        "current_combined": payload.get("current_combined"),
        "projected_combined_if_all_granted": payload.get("projected_combined"),
        "findings": findings,
        "notes": payload.get("notes") or [],
        "disclaimer": "A planning estimate that organizes options — not a VA decision or a promise.",
    }


async def _find_secondary_conditions(ctx: ToolCtx, args: dict) -> dict:
    from ..strategy.rating_rules import find_secondary_opportunities

    opps = find_secondary_opportunities(ctx.dossier.conditions or [])
    return {
        "secondary_opportunities": [
            {
                "primary": o.get("primary"),
                "secondary": o.get("secondary"),
                "why": o.get("rationale") or o.get("body"),
                "reg": o.get("reg"),
                "needs_nexus": o.get("needs_nexus", True),
            }
            for o in opps
        ],
        "disclaimer": "Conditions veterans commonly explore as secondary — talk to your doctor; a nexus opinion is the provider's.",
    }


async def _screen_tdiu(ctx: ToolCtx, args: dict) -> dict:
    from ..strategy.rating_rules import screen_tdiu

    screen = screen_tdiu(ctx.dossier.conditions or [], ctx.dossier.current_combined)
    if not screen:
        return {"applies": False, "note": "Nothing in your record points to the TDIU screen right now."}
    return {
        "applies": True,
        "meets_schedular_gate": screen.get("eligible_schedular"),
        "why": screen.get("why"),
        "what_it_is": screen.get("what_it_is"),
        "evidence": screen.get("evidence"),
        "form": screen.get("form"),
        "reg": screen.get("reg"),
        "disclaimer": "An eligibility SCREEN, not a determination — VA decides unemployability.",
    }


async def _check_readiness(ctx: ToolCtx, args: dict) -> dict:
    # The dossier's conditions already carry the readiness band + what's missing
    # (score_condition ran in build_dossier). Present it plainly.
    return {
        "conditions": [
            {
                "name": c.get("name"),
                "readiness_band": c.get("band"),
                "has_supporting_evidence": c.get("has_have_evidence"),
                "still_needed": c.get("missing") or [],
            }
            for c in (ctx.dossier.conditions or [])
        ],
        "three_elements": ["current diagnosis", "in-service event/injury", "a nexus linking them"],
    }


async def _search_va_rulebook(ctx: ToolCtx, args: dict) -> dict:
    # PUBLIC 38 CFR corpus — not the veteran's record. Grounds the agent's answers on
    # actual regulation text instead of memory.
    query = str(args.get("query") or "").strip()
    if not query:
        return {"cards": []}
    card_type = args.get("card_type") if args.get("card_type") in ("rating_criteria", "process", "rule", "presumptive") else None
    cards = await retrieve_cards(ctx.db, query, k=int(args.get("k") or 4), card_type=card_type)
    return {
        "cards": [
            {
                "title": c.title,
                "diagnostic_code": c.diagnostic_code,
                "source": c.source,
                "excerpt": (c.content or "")[:800],
            }
            for c in cards
        ]
    }


async def _list_deadlines(ctx: ToolCtx, args: dict) -> dict:
    """Same source assembly as GET /deadlines — never re-derive from the dossier
    summary shapes (those drop filed_date / decision_date and would always empty)."""
    from ..deadlines_notify import load_deadlines_for_user

    try:
        deadlines = await load_deadlines_for_user(ctx.db, ctx.uid, today=date.today())
    except Exception:  # noqa: BLE001 — tool must never 500 mid-chat
        log.warning("list_deadlines failed for uid=%s", ctx.uid, exc_info=True)
        return {
            "deadlines": [],
            "note": "Could not load deadlines just now — open Deadlines on the home screen.",
        }
    return {
        "deadlines": [
            {
                "what": dl.title,
                "due_date": dl.due_date if isinstance(dl.due_date, str) else (
                    dl.due_date.isoformat() if dl.due_date else None
                ),
                "days_left": dl.days_left,
                "urgency": dl.urgency,
                "what_to_do": dl.what_to_do,
                "kind": dl.kind,
                "related_route": dl.related_route,
            }
            for dl in deadlines
        ]
    }


async def _check_concurrent_pay(ctx: ToolCtx, args: dict) -> dict:
    d = ctx.dossier
    profile = d.profile or {}
    read = screen_concurrent_pay(
        d.current_combined,
        profile.get("receives_military_retired_pay"),
        profile.get("combat_related_disability"),
    )
    return {
        **read,
        "disclaimer": "An estimate that explains CRDP/CRSC — DFAS and your pay center decide, never a promise.",
    }


async def _preview_form(ctx: ToolCtx, args: dict) -> dict:
    form_id = str(args.get("form_id") or "").strip().lower()
    spec = get_spec(form_id)
    if not spec:
        return {"error": f"Unknown form. Available: {sorted(REGISTRY.keys())}"}
    return {
        "form_id": spec.form_id,
        "we_fill_in": list(spec.auto_filled),
        "you_complete_and_sign": list(getattr(spec, "you_complete", []) or []),
        "note": "Rating Raider pre-fills a DRAFT you review and sign. It never files it, and never fills your SSN or signature.",
    }


async def _review_my_evidence(ctx: ToolCtx, args: dict) -> dict:
    from ..evidence.proactive import evidence_review

    return evidence_review(ctx.dossier)


async def _find_supporting_research(ctx: ToolCtx, args: dict) -> dict:
    # A de-identified Center Deep research link for a nexus theory — the medical
    # literature the PROVIDER cites. No PII in the query.
    from ..evidence.research import nexus_research

    condition = str(args.get("condition") or "").strip()
    if not condition:
        return {"error": "Name the condition to research the causal link for."}
    return nexus_research(
        condition=condition,
        host=ctx.host,
        primary=args.get("primary") or None,
        exposure=args.get("exposure") or None,
    )


async def _search_my_records(ctx: ToolCtx, args: dict) -> dict:
    """Retrieve VERBATIM excerpts from the veteran's OWN uploaded documents (document
    RAG). Reads the veteran's real record → touches_pii=True (stays local)."""
    from ..rag import retrieve_document_chunks

    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "Tell me what to look for in your records (e.g. 'nexus opinion for sleep apnea')."}
    k = min(max(int(args.get("k") or 6), 1), 12)
    try:
        chunks = await retrieve_document_chunks(ctx.db, ctx.uid, query, k=k)
    except Exception:  # noqa: BLE001 — retrieval is best-effort
        return {"query": query, "excerpts": []}
    titles = {str(d.id): (d.title or d.filename) for d in (getattr(ctx.dossier, "documents", None) or [])}
    return {
        "query": query,
        "excerpts": [
            {
                "document_id": str(c.document_id),
                "document": titles.get(str(c.document_id)),
                "char_start": c.char_start,
                "char_end": c.char_end,
                "excerpt": c.content,
            }
            for c in chunks
        ],
        "disclaimer": "These are the veteran's OWN uploaded words, verbatim — surfaced to ground the answer, never interpreted or diagnosed.",
    }


async def _get_case_picture(ctx: ToolCtx, args: dict) -> dict:
    """Return the durable whole-C-file picture (timeline, condition roster with the 3
    SC elements, evidence inventories, contradictions, coverage gaps, honest read-
    completeness). Reads the veteran's record → touches_pii=True."""
    from ..analysis.comprehension import get_case_picture

    picture = await get_case_picture(ctx.db, ctx.uid)
    if not picture:
        return {
            "available": False,
            "note": (
                "Your case picture hasn't been built yet. Upload your records (or your "
                "whole C-file) and I'll assemble the timeline, the condition roster with "
                "each of the three service-connection elements, and the evidence gaps."
            ),
        }
    roster = [
        {
            "name": c.get("name"),
            "diagnostic_code": c.get("diagnostic_code"),
            "rating_percent": c.get("rating_percent"),
            "decision": c.get("decision"),
            "sc_elements": c.get("sc_elements"),
            "missing_elements": c.get("missing_elements") or [],
        }
        for c in (picture.get("condition_roster") or [])
    ]
    return {
        "available": True,
        "read_completeness": picture.get("read_completeness"),
        "condition_roster": roster,
        "timeline": (picture.get("timeline") or [])[:40],
        "coverage_gaps": picture.get("coverage_gaps") or [],
        "contradictions": picture.get("contradictions") or [],
        "counts": {
            "exams": len(picture.get("exam_inventory") or []),
            "nexus_statements": len(picture.get("nexus_inventory") or []),
            "decisions": len(picture.get("decision_inventory") or []),
        },
        "disclaimer": "A durable organization of what the veteran's record SAYS and WHERE it says it — not a VA decision or a medical opinion.",
    }


# Routes Rating Raider may take the veteran to (allowlist — the agent can't navigate anywhere
# arbitrary). Each maps a plain intent to a real SPA route.
_NAV_ROUTES = {
    "battle_plan": "/strategy",
    "deep_dive": "/strategy",
    "evidence_and_analysis": "/actions",
    "your_evidence": "/evidence",
    "conditions": "/conditions",
    "documents": "/documents",
    "filing": "/filing",
    "nexus_letter": "/nexus",
    "buddy_statement": "/buddy",
    "personal_statement": "/statement",
    "tdiu": "/tdiu",
    "dependents": "/dependency",
    "profile": "/profile",
    "workflows": "/workflows",
    "journey": "/journey",
    "deadlines": "/",
    "calculator": "/calculator",
    "presumptives": "/presumptives",
    "appeals": "/appeals",
    "concurrent_pay": "/concurrent-pay",
    "cp_exam": "/cp-companion",
    "cp_companion": "/cp-companion",
    "review_queue": "/review-queue",
    "build_case": "/build-case",
    "analysis": "/analysis",
}


async def _take_me_to(ctx: ToolCtx, args: dict) -> dict:
    """A UI-control action: navigate the veteran to a page. Returns a `ui_action` the
    agent loop re-emits as a UI event the app acts on. The destination is allowlisted."""
    dest = str(args.get("destination") or "").strip().lower()
    route = _NAV_ROUTES.get(dest)
    if not route:
        return {"error": f"Unknown destination. Options: {sorted(_NAV_ROUTES)}"}
    return {"ui_action": {"type": "navigate", "route": route}, "navigated_to": dest}


# form_id → the page that hosts its pre-filled download (a `?form=` param lets the
# page auto-open + scroll to it). These are the fillable forms in pdf/registry.
_FORM_ROUTE = {
    "21-526ez": "/filing", "20-0995": "/filing", "21-4138": "/statement",
    "21-4142": "/filing", "21-8940": "/tdiu", "21-686c": "/dependency",
}


async def _open_form(ctx: ToolCtx, args: dict) -> dict:
    """Open the veteran's PRE-FILLED official form so it's ready to review/print — a
    UI action that navigates to the form's page and tells it to open that form."""
    form_id = str(args.get("form_id") or "").strip().lower()
    spec = get_spec(form_id)
    if not spec or form_id not in _FORM_ROUTE:
        return {"error": f"Unknown form. Fillable: {sorted(_FORM_ROUTE)}"}
    route = f"{_FORM_ROUTE[form_id]}?form={form_id}"
    return {"ui_action": {"type": "navigate", "route": route}, "opened_form": form_id}


async def _list_workflows(ctx: ToolCtx, args: dict) -> dict:
    # The named guided workflows the agent can route a veteran into. Kept in step with
    # frontend/src/lib/workflows.ts; the agent recommends, the veteran drives.
    return {
        "workflows": [
            {"id": "intent_to_file", "when": "want to file but need time to gather records", "does": "lock your effective date (ITF)"},
            {"id": "build_claim", "when": "ready to build a claim", "does": "organize the 3 elements + evidence per condition"},
            {"id": "denied_now_what", "when": "denied or lowballed", "does": "choose the right decision-review lane (Supplemental / HLR / Board) on the 1-year clock"},
            {"id": "am_i_underrated", "when": "think a rating is too low", "does": "decode the decision + compare to the next tier up"},
            {"id": "find_secondaries", "when": "what am I missing", "does": "surface commonly-linked secondary conditions"},
            {"id": "cp_exam_prep", "when": "have a C&P exam coming", "does": "prepare to describe symptoms honestly to your worst day"},
            {"id": "va_math", "when": "confused why 50+30 isn't 80", "does": "the combined-rating math + what actually moves the needle"},
            {"id": "tdiu", "when": "can't hold a job because of service-connected conditions", "does": "screen TDIU (§4.16) + organize 21-8940"},
            {"id": "increase_safely", "when": "condition worsened, worried about reduction", "does": "the increase path + the rating protections"},
            {"id": "presumptive", "when": "exposure (burn pits / Agent Orange / Gulf War / Lejeune)", "does": "check presumptive eligibility"},
            {"id": "add_dependents", "when": "hit 30% or family changed", "does": "add spouse/kids (21-686c)"},
            {"id": "concurrent_pay", "when": "military retiree with a VA rating", "does": "CRDP/CRSC concurrent-pay read"},
        ]
    }


async def _prepare_cp_exam(ctx: ToolCtx, args: dict) -> dict:
    """Deterministic C&P prep snapshot — educational claims prep, not medical advice."""
    from ..analysis.gaps import map_dbq
    from ..kb.store import load_dbq_catalog

    want = (args.get("condition_name") or "").strip().lower()
    catalog = load_dbq_catalog()
    rows = []
    for c in ctx.dossier.conditions or []:
        name = c.get("name") or "condition"
        if want and want not in name.lower():
            continue
        dbq = map_dbq(name, c.get("body_system"), catalog)
        rows.append(
            {
                "name": name,
                "diagnostic_code": c.get("diagnostic_code"),
                "current_rating": c.get("current_rating"),
                "likely_dbq": dbq,
                "still_needed": c.get("missing") or [],
                "how_to_describe": [
                    "Describe worst days and how often they happen.",
                    "Be concrete about frequency, duration, and functional impact (work/home).",
                    "Never exaggerate — credibility matters for the whole claim.",
                    "Bring a short written symptom list so you don't forget under pressure.",
                ],
            }
        )
    if not rows:
        return {
            "available": False,
            "note": (
                "No matching claimed conditions yet. Add conditions (or populate from "
                "records) first, then we can prep C&P exam guidance per condition."
            ),
            "open_route": "/cp-companion",
        }
    return {
        "available": True,
        "conditions": rows[:12],
        "what_to_expect": [
            "The examiner works through a Disability Benefits Questionnaire (DBQ).",
            "They observe and document; the VA rating decision comes later from their findings plus your file.",
            "Exam may be in person or virtual — check the appointment letter.",
        ],
        "open_route": "/cp-companion",
        "disclaimer": (
            "Educational C&P preparation for a VA disability claim — not medical advice, "
            "not a diagnosis, and not a prediction of any rating. Describe symptoms honestly."
        ),
    }


# ── Registry ─────────────────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool(
        "get_my_situation",
        "Get the veteran's current claim picture: their conditions, ratings, combined rating, denials, and what evidence each condition still needs. Call this FIRST to ground yourself before advising.",
        {"type": "object", "properties": {}},
        _get_my_situation,
        touches_pii=True,
    ),
    Tool(
        "run_deep_dive",
        "Run the exhaustive analysis: enumerate every rating the veteran could pursue (direct, increase, secondary, presumptive, concurrent), grounded on 38 CFR, resolve conflicts/pyramiding, and project the combined rating. Use for 'what should I do / am I leaving anything on the table'. Slower — use once when a full picture is needed.",
        {"type": "object", "properties": {}},
        _run_deep_dive,
        touches_pii=True,
    ),
    Tool(
        "find_secondary_conditions",
        "Surface conditions commonly linked as secondary to the veteran's service-connected ones (§3.310), each with the evidence it needs.",
        {"type": "object", "properties": {}},
        _find_secondary_conditions,
        touches_pii=True,
    ),
    Tool(
        "screen_tdiu",
        "Screen whether TDIU (§4.16, pays at the 100% rate without a 100% schedular rating) is worth exploring from the veteran's ratings.",
        {"type": "object", "properties": {}},
        _screen_tdiu,
        touches_pii=True,
    ),
    Tool(
        "check_readiness",
        "Show, per condition, how ready it is to file and exactly what evidence is still missing (the three elements).",
        {"type": "object", "properties": {}},
        _check_readiness,
        touches_pii=True,
    ),
    Tool(
        "search_va_rulebook",
        "Look up the ACTUAL 38 CFR rating criteria / adjudication rules (public corpus) to ground an answer — e.g. what the next PTSD tier requires, or the migraine 'prostrating' criteria. Not the veteran's record.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up, e.g. 'PTSD 70 percent criteria' or 'migraine prostrating'"},
                "card_type": {"type": "string", "enum": ["rating_criteria", "process", "rule", "presumptive"]},
                "k": {"type": "integer", "description": "How many cards (default 4)"},
            },
            "required": ["query"],
        },
        _search_va_rulebook,
        touches_pii=False,
    ),
    Tool(
        "list_deadlines",
        "List the veteran's time-sensitive deadlines (Intent-to-File expiry, appeal windows, dependent retroactivity) with days left — the 1-year clocks they can't afford to miss.",
        {"type": "object", "properties": {}},
        _list_deadlines,
        touches_pii=True,
    ),
    Tool(
        "check_concurrent_pay",
        "Read whether CRDP or CRSC concurrent pay applies (military retirees with a VA rating) and roughly estimate it.",
        {"type": "object", "properties": {}},
        _check_concurrent_pay,
        touches_pii=True,
    ),
    Tool(
        "preview_form",
        "Show what a given official VA form pre-fills automatically vs. what the veteran completes and signs. form_id like '21-526ez', '21-8940', '21-686c', '20-0995', '21-4138', '21-4142'.",
        {"type": "object", "properties": {"form_id": {"type": "string"}}, "required": ["form_id"]},
        _preview_form,
        touches_pii=False,
    ),
    Tool(
        "review_my_evidence",
        "Review the veteran's evidence proactively: what nexus letters / buddy statements / DBQs are ALREADY in their file (to link to the right condition), and where a nexus or buddy statement is obviously needed and obtainable (with a ready-to-draft action). Use to answer 'do I have what I need' or to surface evidence they should add.",
        {"type": "object", "properties": {}},
        _review_my_evidence,
        touches_pii=True,
    ),
    Tool(
        "find_supporting_research",
        "Get a Center Deep deep-research link to pull peer-reviewed medical literature supporting a nexus/causal theory (e.g. sleep apnea secondary to PTSD, a condition linked to an exposure) — the studies a provider cites in the nexus rationale. The query carries NO personal information. Offer this when a nexus letter is the next step.",
        {
            "type": "object",
            "properties": {
                "condition": {"type": "string", "description": "The condition to support"},
                "primary": {"type": "string", "description": "For a secondary theory, the primary service-connected condition it's linked to"},
                "exposure": {"type": "string", "description": "For a presumptive/exposure theory, the exposure (e.g. 'burn pit', 'Agent Orange')"},
            },
            "required": ["condition"],
        },
        _find_supporting_research,
        touches_pii=False,
    ),
    Tool(
        "take_me_to",
        "Navigate the veteran to a page in the app (you drive the screen for them). Use when it helps to SHOW them, e.g. take them to their Claim Plan or the nexus-letter builder. destination is one of: battle_plan, evidence_and_analysis, your_evidence, conditions, documents, filing, nexus_letter, buddy_statement, personal_statement, tdiu, dependents, profile, workflows, journey, calculator, presumptives, appeals, concurrent_pay.",
        {"type": "object", "properties": {"destination": {"type": "string"}}, "required": ["destination"]},
        _take_me_to,
        touches_pii=False,
    ),
    Tool(
        "open_form",
        "Open the veteran's PRE-FILLED official VA form so it's on screen ready to review, print, and sign — you drive them straight to it. form_id one of: 21-526ez (disability claim), 20-0995 (supplemental claim), 21-8940 (TDIU), 21-686c (dependents), 21-4138 (statement), 21-4142 (records release).",
        {"type": "object", "properties": {"form_id": {"type": "string"}}, "required": ["form_id"]},
        _open_form,
        touches_pii=False,
    ),
    Tool(
        "list_workflows",
        "List the guided workflows available so you can route the veteran to the right one for their situation.",
        {"type": "object", "properties": {}},
        _list_workflows,
        touches_pii=False,
    ),
    Tool(
        "search_my_records",
        "Search the veteran's OWN uploaded documents and return VERBATIM excerpts (document RAG) — the actual text of their records. Use to find where something is stated in their file: a nexus opinion, a C&P exam finding, an in-service event, a specific rating. Grounds an answer in their real evidence; the excerpts are their words, never interpreted.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to find in the veteran's records, e.g. 'nexus opinion sleep apnea' or 'tinnitus onset in service'"},
                "k": {"type": "integer", "description": "How many excerpts (default 6, max 12)"},
            },
            "required": ["query"],
        },
        _search_my_records,
        touches_pii=True,
    ),
    Tool(
        "get_case_picture",
        "Get the durable whole-C-file picture built from the veteran's records: a timeline, the condition roster with each of the three service-connection elements (current diagnosis, in-service event, nexus) per condition, the exam/nexus/decision inventories, internal contradictions, the evidence coverage gaps, and an HONEST read-completeness record (how much of the file was read). Use to answer 'what does my whole file show' or 'what's missing' — it organizes the record, it doesn't decide the claim.",
        {"type": "object", "properties": {}},
        _get_case_picture,
        touches_pii=True,
    ),
    Tool(
        "prepare_cp_exam",
        "VA medical/exam prep (educational): for one claimed condition, return the likely DBQ, rating-criteria tiers the examiner assesses, and honest-how-to-describe guidance (worst day, frequency, functional impact). This is C&P exam preparation for claims — not a medical diagnosis, not a rating decision, and not advice to exaggerate. Use when the veteran asks how a C&P works or how to prepare.",
        {
            "type": "object",
            "properties": {
                "condition_name": {
                    "type": "string",
                    "description": "Optional condition name to focus on; otherwise summarize all claimed conditions.",
                },
            },
        },
        _prepare_cp_exam,
        touches_pii=True,
    ),
]

_BY_NAME = {t.name: t for t in TOOLS}


def openai_tool_specs() -> list[dict]:
    """The tools array for the chat-completions `tools` param."""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOLS
    ]


def tool_touches_pii(name: str) -> bool:
    t = _BY_NAME.get(name)
    return bool(t and t.touches_pii)


async def run_tool(name: str, args: dict, ctx: ToolCtx) -> dict:
    """Execute one tool. Never raises — a tool failure is returned to the model as an
    error string so the conversation continues gracefully."""
    tool = _BY_NAME.get(name)
    if not tool:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return await tool.handler(ctx, args or {})
    except Exception:  # noqa: BLE001 — a tool must never crash the chat
        log.warning("raider tool %s failed", name, exc_info=True)
        return {"error": f"'{name}' could not run just now."}

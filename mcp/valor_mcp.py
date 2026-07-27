"""Rating Raider MCP server — the agent-first surface.

Everything the web UI can do, an agent (Claude Desktop/Code, Brigade, any MCP
client) can do through these tools: read/write the veteran's record, run the
deterministic §4.25/§4.26 rating engine, and query the grounded knowledge base.
It is a THIN adapter over the REST API — RLS + audit + the rating math all live
server-side; this file holds no business logic, so "API + MCP for everything"
stays one source of truth.

IMPORTANT — legal lane + agent behavior (see docs/BUILD-SPEC.md, "Legal lane"):
  * Rating Raider is self-help EDUCATIONAL software for a veteran preparing their own
    VA disability claim. It is NOT legal advice, NOT a VA-accredited
    representative/agent under 38 CFR §14.629, and is NOT affiliated with the
    U.S. Department of Veterans Affairs (38 CFR §14.629 restricts paid claim
    preparation/representation to accredited agents — this software is operated
    BY the veteran, TurboTax-style).
  * An agent using these tools must talk in terms of "your claim," "you file,"
    "bring this to your provider/VSO" — never "we'll file for you" or
    "you will get X%". No outcome-contingent language.
  * Every analysis tool below (map_conditions, suggest_secondaries,
    screen_presumptives, analyze_gaps, search_kb/get_kb_card) returns KB
    `source` cites (e.g. "38 CFR §4.130, DC 9411"). PRESERVE those cites
    verbatim when relaying results to a human — never drop or paraphrase away
    the citation.
  * calculate_rating/save_scenario call the server's deterministic 38 CFR
    §4.25/§4.26 engine. Agents must NEVER compute combined ratings, bilateral
    factors, or rounding themselves (by hand or in a sandbox) — always call the
    tool and relay its `steps` log, even for "simple" two-number combinations.
  * Point veterans to a VA-accredited Veterans Service Officer (VSO — VFW, DAV,
    The American Legion, or a state/county veterans office) for filing help,
    and to eCFR / VA.gov to verify current criteria (regulations change).

Run (stdio):  VALOR_API_URL=http://localhost:8001 VALOR_TOKEN=<jwt> python valor_mcp.py
Get a token:  POST /api/auth/login -> access_token  (or /api/auth/register).
Run (SSE):    MCP_TRANSPORT=sse MCP_PORT=8766 python valor_mcp.py   (Brigade's
              MCP registry connects to http://<host>:8766/sse and discovers
              these tools live.)

Remaining intentional MCP gaps (use UI or raw REST — not thin-JSON tools):
  * multipart document upload / binary form PDF streams
  * VA Lighthouse OAuth connect + live VA sync / file-ITF-to-VA
  * SSO login / org & caseload multi-tenant ops
  * billing / credits purchase
  * admin KB refresh, OCR bulk reprocess-ocr, document file download
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("VALOR_API_URL", "http://backend:8000").rstrip("/")
TOKEN = os.environ.get("VALOR_TOKEN", "")

# The global legal-lane disclaimer — identical string to backend/app/main.py's
# DISCLAIMER (this process is a separate container with no import path into the
# backend app, so it is intentionally duplicated here; keep both in sync).
DISCLAIMER = (
    "Rating Raider is self-help educational software. It is not legal advice, not a "
    "VA-accredited representative or agent, and is not affiliated with the U.S. "
    "Department of Veterans Affairs. For free help filing or appealing, use a "
    "VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The American Legion, "
    "or your state/county veterans office. Verify current rating criteria at "
    "eCFR / VA.gov — regulations change."
)

INSTRUCTIONS = (
    "Rating Raider: self-service VA disability compensation tool. The veteran always "
    "drives; you inform and organize, you do not file or represent them (38 CFR "
    f"§14.629). {DISCLAIMER} The rating-calculation tools (calculate_rating, "
    "save_scenario) wrap a deterministic 38 CFR §4.25/§4.26 engine — never do "
    "that arithmetic yourself. Every analysis tool's output carries KB `source` "
    "cites; preserve them verbatim when you relay results to the veteran."
)

# Transport: stdio for Claude Desktop/Code; set MCP_TRANSPORT=sse (or
# streamable-http) to serve over HTTP so Brigade's MCP registry can connect.
mcp = FastMCP(
    "valor-ops",
    instructions=INSTRUCTIONS,
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8766")),
)


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _clean(d: dict) -> dict:
    """Drop None values so partial updates (PATCH/PUT) only send provided fields."""
    return {k: v for k, v in d.items() if v is not None}


async def _api(
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.request(
            method,
            f"{API}/api{path}",
            json=json_body,
            params=_clean(params) if params else None,
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json() if r.content else {}


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


# ── Veteran profile ───────────────────────────────────────────────────────────
@mcp.tool()
async def get_profile() -> str:
    """Get the veteran's profile: service periods, exposures, combat service,
    current combined rating, state, notes. Educational context only — never
    represents VA-of-record data."""
    return _dump(await _api("GET", "/profile"))


@mcp.tool()
async def update_profile(
    service_periods: list[dict] | None = None,
    combat_service: bool | None = None,
    exposures: dict | None = None,
    current_combined_rating: int | None = None,
    state: str | None = None,
    notes: str | None = None,
) -> str:
    """Upsert the veteran's profile (PUT /profile; creates the row if missing).
    service_periods: [{branch, component, start_date, end_date,
    discharge_character}]. exposures: {burn_pits, agent_orange, gulf_war,
    radiation, camp_lejeune, other, locations: [str]}. state: 2-letter USPS
    code. Only pass the fields you want to set — self-reported data the
    veteran is organizing for their own claim, not a system of record."""
    return _dump(
        await _api(
            "PUT",
            "/profile",
            _clean(
                {
                    "service_periods": service_periods,
                    "combat_service": combat_service,
                    "exposures": exposures,
                    "current_combined_rating": current_combined_rating,
                    "state": state,
                    "notes": notes,
                }
            ),
        )
    )


# ── Claimed conditions ────────────────────────────────────────────────────────
@mcp.tool()
async def list_conditions() -> str:
    """List the veteran's claimed conditions (direct/secondary/presumptive/
    increase), with status, ratings, and DBQ form if set."""
    return _dump(await _api("GET", "/conditions"))


@mcp.tool()
async def get_condition(condition_id: str) -> str:
    """Get one claimed condition by id."""
    return _dump(await _api("GET", f"/conditions/{condition_id}"))


@mcp.tool()
async def create_condition(
    name: str,
    body_system: str | None = None,
    diagnostic_code: str | None = None,
    claim_type: str = "direct",
    secondary_to: str | None = None,
    current_rating: int | None = None,
    target_rating: int | None = None,
    status: str = "considering",
    onset_date: str | None = None,
    in_service_event: str | None = None,
    nexus_notes: str | None = None,
    dbq_form: str | None = None,
    notes: str | None = None,
) -> str:
    """Add a condition the veteran is claiming or considering. claim_type:
    direct|secondary|presumptive|increase (secondary_to = id of the primary
    condition it's secondary to). status: considering|gathering_evidence|
    ready_to_file|filed|decided. onset_date: YYYY-MM-DD. This organizes the
    veteran's own claim prep — it does not submit anything to VA."""
    return _dump(
        await _api(
            "POST",
            "/conditions",
            {
                "name": name,
                "body_system": body_system,
                "diagnostic_code": diagnostic_code,
                "claim_type": claim_type,
                "secondary_to": secondary_to,
                "current_rating": current_rating,
                "target_rating": target_rating,
                "status": status,
                "onset_date": onset_date,
                "in_service_event": in_service_event,
                "nexus_notes": nexus_notes,
                "dbq_form": dbq_form,
                "notes": notes,
            },
        )
    )


@mcp.tool()
async def update_condition(
    condition_id: str,
    name: str | None = None,
    body_system: str | None = None,
    diagnostic_code: str | None = None,
    claim_type: str | None = None,
    secondary_to: str | None = None,
    current_rating: int | None = None,
    target_rating: int | None = None,
    status: str | None = None,
    onset_date: str | None = None,
    in_service_event: str | None = None,
    nexus_notes: str | None = None,
    dbq_form: str | None = None,
    notes: str | None = None,
) -> str:
    """Partially update a claimed condition (PATCH) — only pass the fields
    that changed."""
    return _dump(
        await _api(
            "PATCH",
            f"/conditions/{condition_id}",
            _clean(
                {
                    "name": name,
                    "body_system": body_system,
                    "diagnostic_code": diagnostic_code,
                    "claim_type": claim_type,
                    "secondary_to": secondary_to,
                    "current_rating": current_rating,
                    "target_rating": target_rating,
                    "status": status,
                    "onset_date": onset_date,
                    "in_service_event": in_service_event,
                    "nexus_notes": nexus_notes,
                    "dbq_form": dbq_form,
                    "notes": notes,
                }
            ),
        )
    )


@mcp.tool()
async def delete_condition(condition_id: str) -> str:
    """Delete a claimed condition. Irreversible — confirm with the veteran
    before calling this."""
    return _dump(await _api("DELETE", f"/conditions/{condition_id}"))


# ── Evidence ──────────────────────────────────────────────────────────────────
@mcp.tool()
async def list_evidence(condition_id: str) -> str:
    """List evidence items filed under one claimed condition."""
    return _dump(await _api("GET", f"/conditions/{condition_id}/evidence"))


@mcp.tool()
async def add_evidence(
    condition_id: str,
    title: str,
    kind: str = "other",
    status: str = "need",
    source: str | None = None,
    file_ref: str | None = None,
    notes: str | None = None,
) -> str:
    """Add an evidence item to a condition. kind: diagnosis|service_record|
    nexus_letter|dbq|lay_statement|continuity|treatment_record|other. status:
    have|need|requested|not_applicable. Tracks what the veteran has or still
    needs to gather — it is not a document store."""
    return _dump(
        await _api(
            "POST",
            f"/conditions/{condition_id}/evidence",
            {
                "kind": kind,
                "title": title,
                "status": status,
                "source": source,
                "file_ref": file_ref,
                "notes": notes,
            },
        )
    )


@mcp.tool()
async def update_evidence(
    evidence_id: str,
    kind: str | None = None,
    title: str | None = None,
    status: str | None = None,
    source: str | None = None,
    file_ref: str | None = None,
    notes: str | None = None,
) -> str:
    """Partially update an evidence item (e.g. flip status have/need/requested
    as the veteran gathers documents)."""
    return _dump(
        await _api(
            "PATCH",
            f"/evidence/{evidence_id}",
            _clean(
                {
                    "kind": kind,
                    "title": title,
                    "status": status,
                    "source": source,
                    "file_ref": file_ref,
                    "notes": notes,
                }
            ),
        )
    )


@mcp.tool()
async def delete_evidence(evidence_id: str) -> str:
    """Delete an evidence item."""
    return _dump(await _api("DELETE", f"/evidence/{evidence_id}"))


# ── Evidence-gap analysis ─────────────────────────────────────────────────────
@mcp.tool()
async def analyze_gaps(condition_id: str) -> str:
    """Deterministic, rule-based evidence-gap check for one condition (current
    diagnosis / in-service event-nexus / continuity for direct claims;
    primary-link + nexus for secondary; current treatment evidence for
    increase), plus KB-sourced DBQ mapping. Returns gaps (each with a `source`
    cite — preserve it) and the auto-generated checklist items. Educational
    only: tell the veteran to confirm with their provider or a VSO, not a
    determination of what VA will accept."""
    return _dump(await _api("GET", f"/conditions/{condition_id}/gaps"))


# ── Rating engine (deterministic — never do this math yourself) ─────────────
@mcp.tool()
async def calculate_rating(entries: list[dict]) -> str:
    """Calculate a combined VA disability rating. entries:
    [{label, percent, side?, group?}] — side is "left"/"right" for a
    bilateral-candidate extremity entry (both sides present triggers the 38
    CFR §4.26 bilateral factor).

    THE MATH IS THE DETERMINISTIC 38 CFR §4.25/§4.26 ENGINE running server-side
    (backend/app/rating/engine.py) — pairwise combine table with intermediate
    integer rounding, bilateral-factor grouping, descending-severity order,
    and final rounding to the nearest 10 (values ending in 5 round up). AGENTS
    MUST NEVER COMPUTE OR APPROXIMATE THIS ARITHMETIC THEMSELVES, not even for
    "simple" two-number combines — always call this tool and relay its
    `steps` log verbatim so the veteran sees exactly how the number was
    reached. The response also carries educational-only `smc_flags`
    (SMC-S / TDIU threshold pointers) — never phrase these as an entitlement
    determination."""
    return _dump(await _api("POST", "/rating/calculate", {"entries": entries}))


@mcp.tool()
async def list_scenarios() -> str:
    """List the veteran's saved rating what-if scenarios."""
    return _dump(await _api("GET", "/rating/scenarios"))


@mcp.tool()
async def save_scenario(name: str, entries: list[dict]) -> str:
    """Save a named what-if scenario. entries: same shape as calculate_rating.
    The server recomputes the result with the deterministic engine on save —
    it never trusts client-side math."""
    return _dump(
        await _api("POST", "/rating/scenarios", {"name": name, "entries": entries})
    )


@mcp.tool()
async def delete_scenario(scenario_id: str) -> str:
    """Delete a saved rating scenario."""
    return _dump(await _api("DELETE", f"/rating/scenarios/{scenario_id}"))


# ── Knowledge base ────────────────────────────────────────────────────────────
@mcp.tool()
async def search_kb(q: str = "", type: str = "", body_system: str = "") -> str:
    """Search/list KB cards (rating criteria, rules, presumptive lists, DBQs,
    filing-process cards). type: rating_criteria|rule|presumptive|dbq|process.
    Vector search when q is set and embeddings are up, else falls back to an
    ILIKE match. Every card carries a `source` cite (e.g. "38 CFR §4.130, DC
    9411") — preserve it verbatim when relaying a card's content to the
    veteran; this is educational reference material, not a determination."""
    return _dump(
        await _api("GET", "/kb/cards", params={"q": q, "type": type, "body_system": body_system})
    )


@mcp.tool()
async def get_kb_card(card_id: str) -> str:
    """Get one KB card by id (full markdown content + structured tier data +
    its `source` cite — preserve the cite when relaying)."""
    return _dump(await _api("GET", f"/kb/cards/{card_id}"))


@mcp.tool()
async def get_kb_dbq(condition: str) -> str:
    """Look up the DBQ (Disability Benefits Questionnaire) KB card(s) for a
    condition name, for the veteran to bring to their provider."""
    return _dump(await _api("GET", "/kb/dbq", params={"condition": condition}))


# ── LLM+KB analysis (constrained: only cites what the KB actually returned) ──
@mcp.tool()
async def map_conditions(names: list[str] | None = None) -> str:
    """For claimed conditions (or the given condition `names`, if provided
    instead), return likely diagnostic codes, the criteria tier table, the
    evidence each tier needs, and an `under_rated` flag when the current
    rating looks below what the notes suggest. Constrained: every diagnostic
    code/percent is validated against retrieved KB cards (never invented) and
    each item carries a `source` cite — preserve every cite verbatim, and
    relay `under_rated` as "worth discussing with your provider/VSO," never as
    a guaranteed higher rating."""
    body = {"names": names} if names else {}
    return _dump(await _api("POST", "/analysis/map-conditions", body))


@mcp.tool()
async def suggest_secondaries(names: list[str] | None = None) -> str:
    """Suggest plausible secondary conditions from the KB secondary-condition
    map, for claimed/granted conditions (or the given `names`, if provided).
    Each suggestion carries a `rationale` in "discuss with your provider"
    framing and a `source` cite — preserve the cite; never state a secondary
    condition will be granted."""
    body = {"names": names} if names else {}
    return _dump(await _api("POST", "/analysis/secondaries", body))


@mcp.tool()
async def screen_presumptives() -> str:
    """Rule-based screen of the veteran's profile (service periods + exposures)
    against KB presumptive-condition lists (PACT Act/burn pits, Agent Orange,
    Gulf War, radiation, Camp Lejeune). Membership is decided by the rule
    engine, not the LLM. Each match carries a `source` cite — preserve it, and
    frame results as "may qualify for presumptive service connection — confirm
    with a VSO," never as a guarantee."""
    return _dump(await _api("GET", "/analysis/presumptives"))


# ── Packet + filing guide ─────────────────────────────────────────────────────
@mcp.tool()
async def get_packet(condition_id: str) -> str:
    """Get the printable "bring to your provider / DBQ prep" packet for a
    condition: diagnostic code + criteria tiers, evidence on hand vs missing,
    continuity summary (including Glitter Mane data if connected), and
    lay-statement prompts. For the veteran to hand to their provider — not a
    VA submission."""
    return _dump(await _api("GET", f"/packet/{condition_id}"))


@mcp.tool()
async def filing_lanes() -> str:
    """Static KB `process` cards describing the filing lanes: FDC (Fully
    Developed Claim), supplemental claim, Higher-Level Review, Board/AMA
    appeal, effective dates, and CUE (clear and unmistakable error). Reference
    material only — a VSO can help pick the right lane for a given claim."""
    return _dump(await _api("GET", "/filing/lanes"))


# ── Checklist ─────────────────────────────────────────────────────────────────
@mcp.tool()
async def list_checklist(condition_id: str = "") -> str:
    """List checklist items, optionally filtered to one condition_id (omit for
    every item across all conditions)."""
    # The backend validates condition_id as UUID|None — an empty string 422s,
    # so only send the param when a value was actually provided.
    params = {"condition_id": condition_id} if condition_id else None
    return _dump(await _api("GET", "/checklist", params=params))


@mcp.tool()
async def add_checklist_item(
    text: str,
    condition_id: str | None = None,
    category: str | None = None,
    sort: int = 0,
) -> str:
    """Add a checklist item (optionally tied to a condition_id)."""
    return _dump(
        await _api(
            "POST",
            "/checklist",
            {"text": text, "condition_id": condition_id, "category": category, "sort": sort},
        )
    )


@mcp.tool()
async def toggle_checklist_item(item_id: str, done: bool = True) -> str:
    """Set a checklist item's done state (defaults to marking it done; pass
    done=false to un-check). PATCH /checklist/{id} — the backend has no
    read-and-invert toggle, so the value is always sent explicitly."""
    return _dump(await _api("PATCH", f"/checklist/{item_id}", {"done": done}))


@mcp.tool()
async def delete_checklist_item(item_id: str) -> str:
    """Delete a checklist item."""
    return _dump(await _api("DELETE", f"/checklist/{item_id}"))


# ── Claim Plan / strategy (Battle Plan) ───────────────────────────────────────
@mcp.tool()
async def get_strategy() -> str:
    """Get the veteran's Claim Plan (Game Plan): snapshot, coach (do_this_first,
    outstanding, section_guides, interview seed, case_brief), cautions (poking
    the bear), TDIU, reclaim/secondaries, pathways, and priority actions.
    Deterministic core; educational only — never a prediction of what VA will
    do. Prefer this over inventing strategy."""
    return _dump(await _api("GET", "/strategy"))


@mcp.tool()
async def get_case_brief() -> str:
    """Printable case brief one-pager: SC/denied, do-this-first, outstanding,
    cautions, TDIU, duplicate clusters. For veteran or VSO handoff — not a filing."""
    return _dump(await _api("GET", "/strategy/case-brief"))


@mcp.tool()
async def get_interview_seed() -> str:
    """Post-analysis interview seed: opening + gap questions (work, reclaim,
    CFS/fibro, goals). Deterministic; use to start a Rating Raider coach chat."""
    return _dump(await _api("GET", "/strategy/interview-seed"))


@mcp.tool()
async def list_duplicate_conditions() -> str:
    """Cluster similarly named claimed conditions for cleanup. Read-only."""
    return _dump(await _api("GET", "/conditions/duplicates"))


@mcp.tool()
async def park_duplicate_conditions(
    park_ids: list[str],
    keep_id: str | None = None,
    keep_name: str | None = None,
) -> str:
    """Park duplicate condition rows (status=decided, notes tagged). Does not
    change va_status. Confirm with the veteran first — file cleanup only."""
    return _dump(
        await _api(
            "POST",
            "/conditions/park-duplicates",
            _clean(
                {
                    "park_ids": park_ids,
                    "keep_id": keep_id,
                    "keep_name": keep_name,
                }
            ),
        )
    )


@mcp.tool()
async def refresh_strategy() -> str:
    """Re-run Claim Plan firm specialists + briefing (uses the local model) and
    return the enriched plan. Heavier than get_strategy; only call when the
    veteran asks to re-analyze the plan — not on every turn."""
    return _dump(await _api("POST", "/strategy/refresh"))


@mcp.tool()
async def preview_decision_statuses() -> str:
    """Preview va_status updates proposed from formal VA decision letters for
    claimed conditions still marked unknown. Dry-run only — does not write.
    C&P exams are ignored. Educational organizing of the veteran's own letters."""
    return _dump(await _api("GET", "/strategy/decision-statuses"))


@mcp.tool()
async def apply_decision_statuses(dry_run: bool = False) -> str:
    """Apply decision-letter va_status (and SC percent when known) onto claimed
    conditions that are still unknown. Opt-in; never overwrites explicit
    statuses. Pass dry_run=true to preview without writing. Confirm with the
    veteran before apply — this organizes letter facts, not a VA determination."""
    return _dump(
        await _api(
            "POST",
            "/strategy/decision-statuses/apply",
            params={"dry_run": dry_run},
        )
    )


@mcp.tool()
async def get_deep_dive() -> str:
    """Get the cached exhaustive deep-dive findings (if any). Educational rating-
    space review — not a determination."""
    return _dump(await _api("GET", "/strategy/deepdive"))


# ── Full case review (comprehensive analysis) ─────────────────────────────────
@mcp.tool()
async def comprehensive_prerequisites() -> str:
    """What must be true before starting a full multi-step case review
    (documents processed, etc.). Call before start_comprehensive_analysis."""
    return _dump(await _api("GET", "/analysis/comprehensive/prerequisites"))


@mcp.tool()
async def start_comprehensive_analysis() -> str:
    """Durably enqueue the full case review pipeline (assemble → mapping →
    briefing → firm → deep dive → whole-file comprehension). Returns a pollable
    run immediately (HTTP 202). Poll get_latest_analysis_run or
    get_analysis_run. Educational only — does not file anything with VA."""
    return _dump(await _api("POST", "/analysis/comprehensive/start"))


@mcp.tool()
async def get_latest_analysis_run() -> str:
    """Latest comprehensive analysis run status/progress for the veteran."""
    return _dump(await _api("GET", "/analysis/comprehensive/latest"))


@mcp.tool()
async def get_analysis_run(run_id: str) -> str:
    """Poll one comprehensive analysis run by id for live per-step progress."""
    return _dump(await _api("GET", f"/analysis/comprehensive/runs/{run_id}"))


@mcp.tool()
async def cancel_comprehensive_analysis(run_id: str) -> str:
    """Request cooperative cancel of an in-flight comprehensive analysis run
    (POST /analysis/comprehensive/runs/{id}/cancel). Already-terminal runs are
    returned as-is. Educational pipeline only — nothing is filed with VA."""
    return _dump(await _api("POST", f"/analysis/comprehensive/runs/{run_id}/cancel"))


@mcp.tool()
async def get_case_picture() -> str:
    """Structured case picture from analysis (timeline, gaps, decisions summary)
    when available."""
    return _dump(await _api("GET", "/analysis/case-picture"))


@mcp.tool()
async def get_case_candidates(enrich: bool = False) -> str:
    """Conditions the veteran's OWN uploaded records already name, grouped into
    candidates to confirm (GET /analysis/case-candidates). Default enrich=false is
    deterministic alias-collapse only (free). enrich=true runs an optional local
    LLM merge (may cost a credit). Never invents conditions; nothing is claimed
    until the veteran builds a case in the UI/API."""
    return _dump(
        await _api("GET", "/analysis/case-candidates", params={"enrich": enrich})
    )


@mcp.tool()
async def whats_changed() -> str:
    """VA regulatory / rule changes that took effect AFTER this veteran's last
    rating and that touch their conditions or exposures (GET /analysis/whats-changed).
    Deterministic curated facts + source cites — preserve cites; never invent
    rules. needs_rating_date is true when no rating document anchors the compare.
    Educational only — not a guarantee of a higher rating or reopening."""
    return _dump(await _api("GET", "/analysis/whats-changed"))


@mcp.tool()
async def whats_changed_assess(change_id: str) -> str:
    """On-demand person-specific read of one what's-changed item
    (POST /analysis/whats-changed/{id}/assess). Local model when privacy mode is
    on; returns evidence-to-gather framing only — never an entitlement prediction.
    404 if that change no longer matches the veteran's record."""
    return _dump(
        await _api("POST", f"/analysis/whats-changed/{change_id}/assess")
    )


# ── TDIU workspace ────────────────────────────────────────────────────────────
@mcp.tool()
async def get_tdiu_screen() -> str:
    """Educational TDIU (§4.16) screen + evidence guidance. Not an eligibility
    determination — never tell the veteran they qualify or to stop working."""
    return _dump(await _api("GET", "/tdiu"))


@mcp.tool()
async def tdiu_worksheet(
    veteran_name: str = "",
    last_full_time_date: str = "",
    highest_earnings: str = "",
    education: str = "",
    training: str = "",
    jobs: list[dict] | None = None,
    how_conditions_limit_work: str = "",
    doctor_restrictions: str = "",
) -> str:
    """Format the veteran's work history into a print-ready 21-8940-style
    worksheet (POST /tdiu/worksheet). Narrative fields are reproduced VERBATIM —
    never reword employment history or invent medical restrictions. The veteran
    reviews, completes, and signs the official VA Form 21-8940; this tool never
    files with VA and never tells them to stop working. jobs: [{employer,
    job_title, dates, hours_per_week, reason_ended}]."""
    return _dump(
        await _api(
            "POST",
            "/tdiu/worksheet",
            {
                "veteran_name": veteran_name,
                "last_full_time_date": last_full_time_date,
                "highest_earnings": highest_earnings,
                "education": education,
                "training": training,
                "jobs": jobs or [],
                "how_conditions_limit_work": how_conditions_limit_work,
                "doctor_restrictions": doctor_restrictions,
            },
        )
    )


# ── Intent to File (local reminders — not VA Lighthouse submit) ───────────────
@mcp.tool()
async def list_itf() -> str:
    """List Intent-to-File reminder records the veteran saved locally (GET /itf)
    plus the soonest active window. Educational countdown only — does not read or
    submit ITFs to VA (use the VA Connect / Lighthouse path for live VA ITF)."""
    return _dump(await _api("GET", "/itf"))


@mcp.tool()
async def create_itf(
    filed_date: str,
    type: str = "compensation",
    source: str = "manual",
    notes: str | None = None,
) -> str:
    """Save a local ITF reminder (POST /itf). filed_date: YYYY-MM-DD when the
    veteran filed VA Form 0966. type: compensation|pension|survivor. source:
    manual|va. Does NOT submit an ITF to VA — only tracks the one-year window so
    the veteran can file the actual claim (or ask a free VSO) before it expires."""
    return _dump(
        await _api(
            "POST",
            "/itf",
            _clean(
                {
                    "type": type,
                    "filed_date": filed_date,
                    "source": source,
                    "notes": notes,
                }
            ),
        )
    )


@mcp.tool()
async def delete_itf(itf_id: str) -> str:
    """Delete a local ITF reminder record (DELETE /itf/{id}). Irreversible —
    confirm with the veteran. Does not affect any ITF on file with VA."""
    return _dump(await _api("DELETE", f"/itf/{itf_id}"))


# ── Strategy evidence review + form catalog ───────────────────────────────────
@mcp.tool()
async def get_evidence_review() -> str:
    """Proactive evidence picture (GET /strategy/evidence-review): what's already
    in the file to link + what's worth adding (nexus / buddy / DBQ leads).
    Deterministic — no GPU. Educational organization only; never invent medical
    opinions or ghost-write signed statements."""
    return _dump(await _api("GET", "/strategy/evidence-review"))


@mcp.tool()
async def list_forms() -> str:
    """Catalog of official VA forms Rating Raider can pre-fill (GET /forms):
    form_id, edition, OMB, title. Binary PDF fill/download stays in the UI —
    agents use this list to know which form_ids exist for preview/handoff."""
    return _dump(await _api("GET", "/forms"))


@mcp.tool()
async def preview_form(form_id: str) -> str:
    """What fields the server would auto-fill vs leave for the veteran on one
    official form (GET /forms/{form_id}). Labels only — the filled PDF stream is
    not returned over MCP. Educational draft prep; veteran reviews and signs."""
    return _dump(await _api("GET", f"/forms/{form_id}"))


# ── Buddy + nexus briefs (human-sign only) ────────────────────────────────────
@mcp.tool()
async def buddy_guidance() -> str:
    """What makes a strong lay/buddy statement (21-10210). Witness must write and
    sign in their own words — never ghost-sign."""
    return _dump(await _api("GET", "/buddy/guidance"))


@mcp.tool()
async def buddy_situation_brief(
    condition: str,
    veteran_name: str | None = None,
    themes: list[str] | None = None,
    period: str | None = None,
    known_facts: list[str] | None = None,
) -> str:
    """Case-aware hit-list for a buddy/lay witness. Deterministic bullets only —
    the witness still writes, edits, and signs. Never fabricate observations."""
    return _dump(
        await _api(
            "POST",
            "/buddy/situation-brief",
            _clean(
                {
                    "condition": condition,
                    "veteran_name": veteran_name,
                    "themes": themes or [],
                    "period": period,
                    "known_facts": known_facts or [],
                }
            ),
        )
    )


@mcp.tool()
async def buddy_draft(
    witness_name: str,
    witness_relationship: str,
    observations: str,
    veteran_name: str | None = None,
    condition: str | None = None,
    period: str | None = None,
) -> str:
    """Render a 21-10210-style draft for the WITNESS to review, edit into their
    own words, and sign. Never submit to VA; never invent observations."""
    return _dump(
        await _api(
            "POST",
            "/buddy/draft",
            _clean(
                {
                    "witness_name": witness_name,
                    "witness_relationship": witness_relationship,
                    "observations": observations,
                    "veteran_name": veteran_name,
                    "condition": condition,
                    "period": period,
                }
            ),
        )
    )


@mcp.tool()
async def nexus_guidance() -> str:
    """What a medical nexus letter is and what the provider must cover. Template
    guidance only — app never supplies the medical opinion."""
    return _dump(await _api("GET", "/nexus/guidance"))


@mcp.tool()
async def nexus_provider_brief(
    condition: str,
    claim_type: str | None = None,
    secondary_to: str | None = None,
    diagnostic_code: str | None = None,
    prior_denial_notes: str | None = None,
    missing_elements: list[str] | None = None,
    records_to_review: list[str] | None = None,
) -> str:
    """Provider-facing brief: what was missing historically + blank opinion
    scaffold. The clinician writes the rationale and signs — never fill the
    opinion for them."""
    return _dump(
        await _api(
            "POST",
            "/nexus/provider-brief",
            _clean(
                {
                    "condition": condition,
                    "claim_type": claim_type,
                    "secondary_to": secondary_to,
                    "diagnostic_code": diagnostic_code,
                    "prior_denial_notes": prior_denial_notes,
                    "missing_elements": missing_elements or [],
                    "records_to_review": records_to_review or [],
                }
            ),
        )
    )


@mcp.tool()
async def nexus_draft(
    condition: str,
    veteran_name: str | None = None,
    diagnostic_code: str | None = None,
    claim_type: str | None = None,
    in_service_event: str | None = None,
    secondary_to: str | None = None,
    clinical_summary: str | None = None,
) -> str:
    """Nexus letter TEMPLATE for the provider to complete and sign. Opinion is a
    fill-in; rationale left blank. Never fabricate a medical opinion."""
    return _dump(
        await _api(
            "POST",
            "/nexus/draft",
            _clean(
                {
                    "condition": condition,
                    "veteran_name": veteran_name,
                    "diagnostic_code": diagnostic_code,
                    "claim_type": claim_type,
                    "in_service_event": in_service_event,
                    "secondary_to": secondary_to,
                    "clinical_summary": clinical_summary,
                }
            ),
        )
    )


# ── Documents (list/reprocess/decode — multipart upload stays UI/API) ─────────
@mcp.tool()
async def list_documents() -> str:
    """List the veteran's uploaded documents and processing status. Multipart
    upload remains UI/API; agents reprocess failed docs and decode decision
    letters via the tools below."""
    return _dump(await _api("GET", "/documents"))


@mcp.tool()
async def reprocess_document(document_id: str, force_ocr: bool = False) -> str:
    """Re-queue one document through the intake pipeline
    (POST /documents/{id}/reprocess). Reuses already-parsed text unless
    force_ocr=true (which clears stored text so the file is re-read — needs the
    stored file). Educational processing only; does not file with VA."""
    return _dump(
        await _api(
            "POST",
            f"/documents/{document_id}/reprocess",
            params={"force_ocr": force_ocr},
        )
    )


@mcp.tool()
async def reprocess_failed_documents() -> str:
    """Re-queue every failed document (POST /documents/reprocess-failed), e.g.
    after an LLM-gateway outage during a bulk upload. Returns {requeued: N}.
    Docs with neither file nor text are left failed."""
    return _dump(await _api("POST", "/documents/reprocess-failed"))


@mcp.tool()
async def list_decodable_documents() -> str:
    """List ready documents that look like VA rating decisions / decision letters
    (GET /documents/decodable) — candidates for decode_document."""
    return _dump(await _api("GET", "/documents/decodable"))


@mcp.tool()
async def decode_document(document_id: str) -> str:
    """Decode an uploaded VA decision letter into plain English + AMA appeal
    lanes (POST /documents/{id}/decode). Runs on stored text; caches the result.
    Educational only — never files or appeals. Preserve any source cites; frame
    next steps as options for the veteran or a free VSO, never as a guarantee."""
    return _dump(await _api("POST", f"/documents/{document_id}/decode"))


@mcp.tool()
async def get_decode(document_id: str) -> str:
    """Return the cached decision-letter decode (GET /documents/{id}/decode).
    404 if never decoded — call decode_document first."""
    return _dump(await _api("GET", f"/documents/{document_id}/decode"))


if __name__ == "__main__":
    # MCP_TRANSPORT=stdio (default) | sse | streamable-http
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))

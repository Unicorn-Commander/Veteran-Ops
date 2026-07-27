"""Claim Plan coach layer — turns Game Plan + dossier facts into:

  * do_this_first / then / parked moves
  * outstanding open items
  * per-section guides (what / why / do / outstanding)
  * duplicate-condition clusters
  * agent interview seed questions (deterministic gap Qs)

Pure functions (no DB, no LLM). Educational only — organizes next steps; never
files or predicts VA outcomes.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .rating_rules import _norm

_HISTORY_RE = re.compile(r"^\s*history of\s+", re.IGNORECASE)
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")
_WS = re.compile(r"\s+")

# Cluster keys for duplicate detection (keyword → family)
_DUP_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cfs", ("chronic fatigue", "me/cfs", "myalgic encephalomyelitis", "cfs", "post-viral fatigue")),
    ("anxiety", ("anxiety", "gad", "generalized anxiety", "unspecified anxiety")),
    ("depression", ("depression", "depressive", "mdd", "major depressive")),
    ("ptsd", ("ptsd", "post-traumatic", "posttraumatic")),
    ("knee_left", ("left knee",)),
    ("knee_right", ("right knee",)),
    ("knee_both", ("both knees", "bilateral knee", "left knee and right knee")),
    ("knee_generic", ("knee",)),
    ("fibro", ("fibromyalgia",)),
    ("mono", ("mononucleosis", "epstein-barr", "ebv")),
    ("gerd", ("gerd", "reflux", "acid reflux")),
)


def _cluster_key(name: str | None) -> str:
    n = _norm(name)
    n = _HISTORY_RE.sub("", n)
    n = _PAREN_RE.sub(" ", n)
    n = _WS.sub(" ", n).strip()
    for family, kws in _DUP_FAMILIES:
        if any(kw in n for kw in kws):
            # Prefer specific knee sides over generic
            if family.startswith("knee") and family != "knee_generic":
                return family
            if family == "knee_generic":
                # only if no side word
                if "left" not in n and "right" not in n:
                    return family
                continue
            return family
    # fallback: first 3 tokens
    toks = [t for t in n.split() if len(t) > 2][:3]
    return " ".join(toks) if toks else n or "unknown"


def find_duplicate_clusters(conditions: list[dict]) -> list[dict]:
    """Group claimed conditions that look like the same contention under many names."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in conditions:
        buckets[_cluster_key(c.get("name"))].append(c)
    out: list[dict] = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        names = [m.get("name") or "" for m in members]
        sc = [m for m in members if (m.get("va_status") or "") == "service_connected"]
        denied = [m for m in members if (m.get("va_status") or "") == "denied"]
        keep = None
        if sc:
            # keep highest rated SC
            keep = max(sc, key=lambda m: m.get("current_rating") or 0)
        elif denied:
            keep = denied[0]
        else:
            keep = members[0]
        park = [m for m in members if m is not keep]
        park_names = [m.get("name") or "" for m in park]
        status_bit = ""
        if keep.get("va_status") and keep.get("va_status") != "unknown":
            status_bit = f" ({keep.get('va_status')}"
            if keep.get("current_rating"):
                status_bit += f" {keep.get('current_rating')}%"
            status_bit += ")"
        out.append({
            "key": f"dup:{key}",
            "family": key,
            "count": len(members),
            "keep_name": keep.get("name") or "",
            "keep_id": keep.get("id"),
            "keep_va_status": keep.get("va_status") or "unknown",
            "park_names": park_names,
            "park_ids": [m.get("id") for m in park if m.get("id")],
            "title": f"{len(members)} similar names for “{key.replace('_', ' ')}”",
            "body": (
                f"Keep “{keep.get('name')}” as the working row{status_bit}. "
                f"Park or merge the other {len(park)}: "
                + ", ".join(park_names[:6])
                + ". Duplicates confuse readiness and secondaries — cleaning them up is "
                "organization, not a VA filing."
            ),
            "severity": "high" if len(members) >= 4 else "medium",
            "link": "/conditions",
        })
    out.sort(key=lambda d: (-d["count"], d["family"]))
    return out


def _action_to_move(a: dict, *, tier: str) -> dict:
    return {
        "id": f"act:{(a.get('category') or 'x')}:{(a.get('condition_name') or a.get('title') or '')[:40]}",
        "tier": tier,  # first | then | parked
        "title": a.get("title") or "Next step",
        "why": a.get("why") or "",
        "link": a.get("link"),
        "category": a.get("category"),
        "condition_name": a.get("condition_name"),
        "impact": a.get("impact") or "medium",
        "kind": "action",
    }


def _is_parked_row(c: dict) -> bool:
    notes = (c.get("notes") or "").upper()
    if "[PARKED" in notes:
        return True
    # status decided + not increase and not SC is often parked/noise
    if (c.get("status") or "") == "decided" and (c.get("va_status") or "unknown") == "unknown":
        return True
    return False


def _reclaim_family(secondary: str | None) -> str:
    return _cluster_key(secondary or "")


def build_outstanding(
    *,
    plan: dict,
    conditions: list[dict],
    denials: list[dict] | None = None,
    decision_status_pending: int = 0,
) -> list[dict]:
    """Quieter open-items list: collapse reclaim families, few gaps, cautions last."""
    items: list[dict] = []
    denials = denials or []
    reclaim_secs: set[str] = set()

    # ── Reclaim: one card per family (anxiety ×3 → one row) ─────────────────
    reclaim_by_family: dict[str, list[dict]] = defaultdict(list)
    for o in plan.get("opportunities") or []:
        if o.get("kind") != "reclaim":
            continue
        fam = _reclaim_family(o.get("secondary"))
        reclaim_by_family[fam].append(o)
        reclaim_secs.add(_norm(o.get("secondary")))

    for fam, group in reclaim_by_family.items():
        primary_o = group[0]
        extras = [g.get("secondary") or "" for g in group[1:]]
        title = primary_o.get("title") or f"Reclaim {primary_o.get('secondary')}"
        if extras:
            title = (
                f"Reclaim {primary_o.get('secondary')} "
                f"(+{len(extras)} similar name{'' if len(extras) == 1 else 's'})"
            )
        why = (primary_o.get("body") or "")[:220]
        if extras:
            why += f" Same theory covers: {', '.join(extras[:4])}."
        items.append({
            "id": f"reclaim_family:{fam}",
            "kind": "reclaim",
            "severity": "high",
            "title": title,
            "why": why[:320],
            "link": (
                f"/nexus?condition={_q(primary_o.get('secondary'))}"
                f"&claim_type=secondary&secondary_to={_q((primary_o.get('primary') or [''])[0])}"
                f"&brief=1&prior_denial=1"
            ),
            "checklist": (primary_o.get("attach_checklist") or [])[:5],
            "status": "not_started",
            "tier": "primary",
        })

    tdiu = plan.get("tdiu")
    if tdiu:
        items.append({
            "id": "tdiu",
            "kind": "tdiu",
            "severity": "high" if tdiu.get("eligible_schedular") else "medium",
            "title": (
                "Build TDIU work history (schedular door open)"
                if tdiu.get("eligible_schedular")
                else "Review TDIU — near threshold"
            ),
            "why": (
                "TDIU pays at 100% when SC disabilities block substantially gainful work. "
                "Organize jobs, side gigs, and why work stopped — before you file 21-8940."
            )[:280],
            "link": "/tdiu",
            "checklist": (tdiu.get("evidence") or [])[:4],
            "status": "not_started",
            "tier": "primary",
        })

    # ── Evidence gaps: max 3, skip parked + reclaim targets + duplicate noise ─
    gap_n = 0
    seen_gap_family: set[str] = set()
    for c in conditions:
        if gap_n >= 3:
            break
        if _is_parked_row(c) or is_parked_granted(c):
            continue
        missing = c.get("missing") or []
        if not missing:
            continue
        name_n = _norm(c.get("name"))
        # Already covered by a reclaim card
        if any(name_n and (name_n in rs or rs in name_n) for rs in reclaim_secs if rs):
            continue
        fam = _cluster_key(c.get("name"))
        if fam in seen_gap_family:
            continue
        seen_gap_family.add(fam)
        gap_n += 1
        items.append({
            "id": f"gap:{c.get('id') or c.get('name')}",
            "kind": "evidence_gap",
            "severity": "medium",
            "title": f"Still need for {c.get('name')}: {', '.join(missing[:2])}",
            "why": "Close these elements before treating this row as file-ready.",
            "link": f"/conditions/{c['id']}" if c.get("id") else "/conditions",
            "checklist": list(missing)[:4],
            "status": "not_started",
            "tier": "primary" if gap_n <= 2 else "more",
        })

    if decision_status_pending > 0:
        items.append({
            "id": "decision_statuses",
            "kind": "reconcile",
            "severity": "medium",
            "title": f"Apply {decision_status_pending} decision-letter statuses",
            "why": "One click aligns Conditions with formal grants/denials (unknown only).",
            "link": "/strategy",
            "checklist": [],
            "status": "not_started",
            "tier": "primary",
        })

    # Top 1–2 duplicate clusters only
    for d in find_duplicate_clusters(conditions)[:2]:
        if d["count"] < 3 and d.get("severity") != "high":
            # keep high-count only in primary
            tier = "more"
        else:
            tier = "primary" if d["count"] >= 4 else "more"
        items.append({
            "id": d["key"],
            "kind": "duplicate",
            "severity": d["severity"],
            "title": d["title"],
            "why": (
                f"Keep “{d['keep_name']}”; park {len(d['park_names'])} lookalikes so the plan stays readable."
            ),
            "link": "/conditions?dupes=1",
            "checklist": [f"Keep: {d['keep_name']}", *[f"Park: {n}" for n in d["park_names"][:3]]],
            "status": "not_started",
            "tier": tier,
        })

    # Cautions → more (informational), max 2
    for c in (plan.get("cautions") or [])[:2]:
        if c.get("kind") not in ("tdiu_employment", "filing_tradeoff", "pyramiding"):
            continue
        items.append({
            "id": c.get("key") or c.get("title"),
            "kind": "caution",
            "severity": "low",
            "title": f"Before filing: {c.get('title')}",
            "why": (c.get("body") or "")[:200],
            "link": "/tdiu" if c.get("kind") == "tdiu_employment" else "/strategy#cautions",
            "checklist": [],
            "status": "informational",
            "tier": "more",
        })

    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        iid = str(it.get("id") or "")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        out.append(it)

    # primary first, then severity
    tier_r = {"primary": 0, "more": 1}
    sev_r = {"high": 0, "medium": 1, "low": 2}
    out.sort(
        key=lambda x: (
            tier_r.get(x.get("tier") or "more", 1),
            sev_r.get(x.get("severity") or "medium", 1),
        )
    )
    return out


def is_parked_granted(c: dict) -> bool:
    return (c.get("va_status") or "") == "service_connected" and (c.get("claim_type") or "") != "increase"


def _q(s: str | None) -> str:
    from urllib.parse import quote
    return quote(str(s or ""), safe="")


def _score_action(a: dict, *, has_itf: bool, has_reclaim: bool) -> tuple[int, str]:
    """Higher score = better Do this first. Returns (score, plain-language reason)."""
    cat = (a.get("category") or "").lower()
    title = (a.get("title") or "").lower()
    link = (a.get("link") or "").lower()

    if cat == "reclaim" or "reclaim" in title:
        # After ITF (if needed), reclaim is the highest-leverage claim work.
        return (
            94 if not has_itf else 100,
            "A denied condition may reopen on a new secondary theory — get the provider brief / nexus path started.",
        )
    if "tdiu" in title or link.startswith("/tdiu"):
        return (
            92 if "work" in title else 88,
            "Your ratings put TDIU in play; the employment record is usually the missing pillar.",
        )
    if cat == "protect_backpay" or "intent to file" in title or link.startswith("/itf"):
        if has_itf:
            return (40, "You already have date-protection context; other steps matter more now.")
        # Missing ITF: lock the date first, then reclaim/TDIU in "Then".
        return (
            98,
            "File an Intent to File first — it can lock an effective date for a year while you build reclaim/TDIU evidence.",
        )
    if cat == "appeal" or "supplemental" in title:
        return (55, "A Supplemental path needs new evidence — queue after reclaim/TDIU framing.")
    if cat == "close_gap" or "diagnosis" in title or "nexus" in title:
        return (50, "Close a concrete evidence gap on one condition.")
    if cat == "file":
        return (60, "Core evidence looks ready — filing protects the date for that row.")
    if a.get("impact") == "high":
        return (45, "High-impact step from your plan.")
    return (20, "Lower-priority cleanup or exploration.")


def build_moves(plan: dict) -> dict:
    """Rank priority_actions into first / then / parked with clear why-this-first."""
    actions = list(plan.get("priority_actions") or [])
    active_itf = (plan.get("snapshot") or {}).get("active_itf")
    has_itf = bool(active_itf)
    has_reclaim = any(
        (a.get("category") == "reclaim") or ("reclaim" in (a.get("title") or "").lower())
        for a in actions
    )
    # Also from opportunities if actions lag
    if not has_reclaim:
        has_reclaim = any(
            o.get("kind") == "reclaim" for o in (plan.get("opportunities") or [])
        )

    scored: list[tuple[int, str, dict]] = []
    for a in actions:
        score, reason = _score_action(a, has_itf=has_itf, has_reclaim=has_reclaim)
        # Prefer single reclaim over three near-ties: slight boost if only reclaim
        scored.append((score, reason, a))
    scored.sort(key=lambda t: -t[0])

    # Dedupe near-duplicate reclaim titles — keep highest score only for reclaim cat
    seen_reclaim = False
    filtered: list[tuple[int, str, dict]] = []
    for score, reason, a in scored:
        is_rec = (a.get("category") == "reclaim") or ("reclaim" in (a.get("title") or "").lower())
        if is_rec:
            if seen_reclaim:
                continue
            seen_reclaim = True
        filtered.append((score, reason, a))

    if not filtered:
        return {"do_this_first": None, "then": [], "parked": [], "do_this_first_reason": None}

    top_score, top_reason, top_a = filtered[0]
    first_move = _action_to_move(top_a, tier="first")
    # Enrich why with ranking reason when the action why is thin
    if top_reason and (
        not first_move.get("why") or len(first_move.get("why") or "") < 40
    ):
        first_move["why"] = top_reason
    else:
        first_move["why"] = f"{top_reason} {first_move.get('why') or ''}".strip()

    then = [_action_to_move(a, tier="then") for _, _, a in filtered[1:5]]
    parked = [_action_to_move(a, tier="parked") for _, _, a in filtered[5:12]]

    return {
        "do_this_first": first_move,
        "do_this_first_reason": top_reason,
        "then": then,
        "parked": parked,
    }


def build_section_guides(plan: dict, outstanding: list[dict]) -> list[dict]:
    """Per Claim Plan section: what / why / do / outstanding_ids."""
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for it in outstanding:
        by_kind[it.get("kind") or "other"].append(it)

    tdiu = plan.get("tdiu")
    cautions = plan.get("cautions") or []
    opps = plan.get("opportunities") or []
    reclaim = [o for o in opps if o.get("kind") == "reclaim"]

    guides = [
        {
            "id": "overview",
            "title": "Your next move",
            "what": "The single best next step from everything in your file.",
            "why": "A long plan is useless if you don’t know where to start.",
            "do": "Do the top action, then work the “Then” list. Use Outstanding for the full queue.",
            "outstanding_ids": [it["id"] for it in outstanding[:3]],
            "status": "action" if outstanding else "clear",
        },
        {
            "id": "cautions",
            "title": "Poking the bear",
            "what": "Trade-offs before you file — pyramiding, reduction risk, CFS/fibro, TDIU work rules.",
            "why": "Filing can reopen settled ratings or confuse symptom sets; this is education, not a bar.",
            "do": (
                "Read each caution before filing related claims. Open TDIU workspace if employment is flagged."
                if cautions else
                "Nothing flagged — no bear trade-off on file right now."
            ),
            "outstanding_ids": [it["id"] for it in by_kind.get("caution", [])],
            "status": "action" if cautions else "clear",
        },
        {
            "id": "opportunities",
            "title": "Reclaim & under-claimed",
            "what": "Denied claims that may reopen on a new theory, or separate ratings you may be missing.",
            "why": "A denial on a direct theory is not the end — secondary theories and Esteban separations are common wins.",
            "do": (
                f"Start with reclaim: {reclaim[0].get('secondary')} — provider brief, then Supplemental path."
                if reclaim else
                "Review under-rated / secondary opportunities with a VSO when ready."
            ),
            "outstanding_ids": [it["id"] for it in outstanding if it.get("kind") in ("reclaim", "opportunity")],
            "status": "action" if reclaim or opps else "clear",
        },
        {
            "id": "pathways",
            "title": "Pathways & TDIU",
            "what": "Strategic filing lanes and unemployability education.",
            "why": "Order of filing and TDIU work evidence change effective dates and pay rate.",
            "do": (
                "Open TDIU workspace and build work chronology before filing TDIU."
                if tdiu else
                "Use the recommended pathway when evidence is ready."
            ),
            "outstanding_ids": [it["id"] for it in by_kind.get("tdiu", [])],
            "status": "action" if tdiu else "informational",
        },
        {
            "id": "actions",
            "title": "Full action list",
            "what": "Every ranked next step (including lower-priority).",
            "why": "Backup queue after you finish Do this first + Then.",
            "do": "Work top to bottom; skip items that no longer apply.",
            "outstanding_ids": [],
            "status": "informational",
        },
        {
            "id": "deep-dive",
            "title": "Deep dive",
            "what": "Exhaustive rating-space review (cached or re-run).",
            "why": "Catches theories the fast plan may not emphasize.",
            "do": "Skim high-severity findings; don’t re-run unless records changed.",
            "outstanding_ids": [],
            "status": "informational",
        },
    ]
    return guides


def build_interview_seed(
    *,
    plan: dict,
    conditions: list[dict],
    outstanding: list[dict],
) -> dict:
    """Deterministic post-analysis interview: opening + gap questions only."""
    questions: list[dict] = []
    tdiu = plan.get("tdiu")
    if tdiu:
        questions.append({
            "id": "work_history",
            "topic": "TDIU / work",
            "question": (
                "In the last 12 months, about how many hours per week have you been able to work "
                "for pay (including side gigs or intermittent federal work)? What stopped or limited each job?"
            ),
            "why": "TDIU turns on substantially gainful employment — only you know the work story.",
            "maps_to": "tdiu",
        })
    reclaim = [o for o in (plan.get("opportunities") or []) if o.get("kind") == "reclaim"]
    if reclaim:
        sec = reclaim[0].get("secondary") or "the denied condition"
        prim = (reclaim[0].get("primary") or ["your service-connected condition"])[0]
        questions.append({
            "id": "reclaim_nexus",
            "topic": "Reclaim / secondary",
            "question": (
                f"For {sec}: has a provider linked it to {prim}, or is that still missing? "
                "Who is your treating clinician for this?"
            ),
            "why": "A secondary reclaim usually needs a medical nexus opinion.",
            "maps_to": reclaim[0].get("key") or "reclaim",
        })
    fibro = any("fibro" in _norm(c.get("name")) for c in conditions)
    cfs = any(
        any(k in _norm(c.get("name")) for k in ("fatigue", "cfs", "encephalomyelitis"))
        for c in conditions
    )
    if fibro and cfs:
        questions.append({
            "id": "cfs_fibro_split",
            "topic": "CFS vs fibromyalgia",
            "question": (
                "Do you have medical notes that separate post-exertional fatigue (CFS picture) "
                "from widespread tender-point pain (fibromyalgia picture), or do they blur together?"
            ),
            "why": "Separate ratings need distinct manifestations — filing both without that can poke the bear.",
            "maps_to": "filing_tradeoff:cfs_fibro",
        })
    # Knee denied
    if any(
        "knee" in _norm(c.get("name")) and (c.get("va_status") or "") == "denied"
        for c in conditions
    ):
        questions.append({
            "id": "knee_new_evidence",
            "topic": "Knee reclaim",
            "question": (
                "For your knees: what current symptoms do you have, and do you have imaging or "
                "records from after the 2016 denial that VA may not have fully weighed?"
            ),
            "why": "Supplemental claims need new and relevant evidence.",
            "maps_to": "knee",
        })
    goals = {
        "id": "goals",
        "topic": "Goals",
        "question": (
            "What matters most right now: protecting your CFS rating, pursuing TDIU, "
            "reclaiming denied conditions, or cleaning the file for a VSO?"
        ),
        "why": "Your goal order changes which path we emphasize.",
        "maps_to": "overview",
    }
    questions.append(goals)

    first = (build_moves(plan).get("do_this_first") or {}).get("title") or "organize your next claim step"
    opening = (
        "I’ve reviewed your organized claim file (conditions, decisions, and plan signals). "
        "Before we lock a recommended order of work, I need a few facts only you know — "
        "nothing here is a VA decision or legal advice. "
        f"Right now the top candidate next step is: {first}. "
        "I’ll ask only about gaps that change the plan."
    )
    closing = (
        "Thanks — with those answers I can tighten your Outstanding list and Claim Plan. "
        "Open Claim Plan for Do this first, or keep asking me here."
    )
    return {
        "mode": "post_analysis",
        "opening": opening,
        "questions": questions[:6],
        "closing_hint": closing,
        "starter_user_message": (
            "I just finished a full case review. Please interview me about the real gaps "
            "in my file (work history, secondary nexus, CFS vs fibro, knee evidence, goals) "
            "and then give me an ordered next-step plan. Ask one question at a time."
        ),
    }


def build_case_brief(
    *,
    plan: dict,
    conditions: list[dict],
    outstanding: list[dict],
    moves: dict,
    profile_summary: str | None = None,
) -> dict:
    """Printable one-pager structure for case brief."""
    sc = [c for c in conditions if (c.get("va_status") or "") == "service_connected"]
    denied = [c for c in conditions if (c.get("va_status") or "") == "denied"]
    first = moves.get("do_this_first")
    return {
        "title": "Case brief — for you or a VSO",
        "disclaimer": (
            "Educational self-help organization of the veteran’s own records. "
            "Not legal advice; not a VA determination. Veteran-Ops does not file claims."
        ),
        "profile_summary": profile_summary or "",
        "snapshot": plan.get("snapshot") or {},
        "service_connected": [
            {
                "name": c.get("name"),
                "rating": c.get("current_rating"),
                "dc": c.get("diagnostic_code"),
            }
            for c in sc
        ],
        "denied": [{"name": c.get("name"), "dc": c.get("diagnostic_code")} for c in denied[:20]],
        "do_this_first": first,
        "then": moves.get("then") or [],
        "outstanding_top": outstanding[:8],
        "cautions": [
            {"title": c.get("title"), "kind": c.get("kind"), "reg": c.get("reg")}
            for c in (plan.get("cautions") or [])
        ],
        "tdiu": plan.get("tdiu"),
        "duplicates": find_duplicate_clusters(conditions)[:5],
    }


def enrich_plan_with_coach(
    plan: dict,
    *,
    conditions: list[dict],
    denials: list[dict] | None = None,
    decision_status_pending: int = 0,
    profile_summary: str | None = None,
) -> dict:
    """Mutate/return plan dict with coach fields (additive)."""
    outstanding = build_outstanding(
        plan=plan,
        conditions=conditions,
        denials=denials,
        decision_status_pending=decision_status_pending,
    )
    moves = build_moves(plan)
    primary = [o for o in outstanding if (o.get("tier") or "primary") == "primary"]
    more = [o for o in outstanding if (o.get("tier") or "primary") != "primary"]
    # Cap primary rail so the UI stays scannable
    if len(primary) > 5:
        more = primary[5:] + more
        primary = primary[:5]
    actionable = [o for o in outstanding if o.get("status") != "informational"]
    plan["coach"] = {
        **moves,
        "outstanding": outstanding,
        "outstanding_primary": primary,
        "outstanding_more": more,
        "outstanding_count": len(actionable),
        "section_guides": build_section_guides(plan, outstanding),
        "duplicates": find_duplicate_clusters(conditions),
        "interview": build_interview_seed(
            plan=plan, conditions=conditions, outstanding=outstanding
        ),
        "case_brief": build_case_brief(
            plan=plan,
            conditions=conditions,
            outstanding=outstanding,
            moves=moves,
            profile_summary=profile_summary,
        ),
        "post_analysis_cta": {
            "title": "Talk through your plan first",
            "body": (
                "Rating Raider can ask a few gap questions (work, nexus, goals), "
                "then send you to Claim Plan with a clear Do this first."
            ),
            "interview_path": "/raider?mode=post_analysis&from=analysis",
            "plan_path": "/strategy?from=interview",
        },
    }
    # Mirror do_this_first onto focus if stronger
    if moves.get("do_this_first"):
        m = moves["do_this_first"]
        plan["focus"] = {
            "title": m.get("title"),
            "why": m.get("why"),
            "link": m.get("link"),
        }
    return plan

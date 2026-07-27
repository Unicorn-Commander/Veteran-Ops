"""The Battle Plan engine — PURE, deterministic (no DB, no LLM, no clock).

`build_game_plan(...)` takes plain data the router gathered and returns the locked
`GamePlanOut` shape (docs/WAVE8-SPEC.md). It reuses the frozen §4.25 combine
(rating/engine.py) for estimated combined ratings and the readiness bands already
computed per condition — it never re-derives evidence rules.

LEGAL LANE (this engine is the riskiest surface for it):
- No outcome promises. No "you will get / you qualify for / this guarantees."
- Every estimated_combined is labeled: computed with §4.25 from the veteran's OWN
  target ratings, and "not a prediction of what VA will decide."
- Ranking is by evidence-readiness and known VA process, NOT by predicting VA.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..rating.engine import combine
from .rating_rules import (
    cautions_for,
    is_already_granted,
    opportunities_for,
    screen_tdiu,
)

# Plain-English of each missing §3.303 element (kept local so the engine doesn't
# couple to the appeals module; must read the same as it does there).
_MISSING_PLAIN = {
    "current_disability": "a current, diagnosed disability",
    "in_service_event": "an in-service event, injury, or exposure",
    "nexus": 'a medical link ("nexus") connecting the two',
}

# "Ready to file" = EVERY core §3.303 element identified. A "strong" band (score
# 67–99) still has one element missing, so it is NOT ready — it belongs in the
# strengthen-first path. Only "complete" (100%, missing == []) is file-ready; this
# also keeps `ready` and `with_gaps` disjoint (no condition is both).
_READY_BANDS = {"complete"}
_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}
_CATEGORY_RANK = {
    "protect_backpay": 0,
    # Reclaim (new secondary theory after denial) ranks with appeals — it must
    # not fall behind a long list of close_gap / file rows for duplicate names.
    "reclaim": 1,
    "appeal": 2,
    "file": 3,
    "close_gap": 4,
    "add_condition": 5,
}

# Readiness band → warm, plain-English label for the at-a-glance condition list.
_BAND_LABELS = {
    "complete": "Ready to file",
    "strong": "Almost there",
    "building": "Coming together",
    "early": "Just getting started",
}

_CLAIM_TYPE_LABELS = {
    "direct": "Direct",
    "secondary": "Secondary",
    "presumptive": "Presumptive",
    "increase": "Increase",
}

_NOT_A_PREDICTION = (
    "This is not a prediction of what VA will decide — it is §4.25 math on the "
    "ratings you set."
)

_DISCLAIMER = (
    "Your Claim Plan is educational self-help, not legal advice and not a prediction "
    "of VA's decision. Veteran-Ops is not a VA-accredited representative and never "
    "files, appeals, or decides anything for you. These are options to consider — you "
    "choose your path. A free VA-accredited VSO can review your specific situation."
)

_VSO_REFERRAL = (
    "A VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The American Legion, "
    "or your state/county veterans office — will review your claim and help you decide "
    "a strategy for free. You never have to pay for help with a VA claim."
)

_SOURCE_NOTE = (
    "Built from what you've entered: your conditions, evidence, readiness, any decoded "
    "decision letters, and your profile. Nothing here is sent to VA."
)


def merge_denied_conditions(denials: list[dict], conditions: list[dict]) -> list[dict]:
    """Fold conditions the veteran (or a VA reconciliation) marked va_status='denied'
    into the denial list decoded from decision letters — deduped by normalized name so
    a condition that appears in BOTH is listed once (the decoded letter, added first,
    wins because it may carry missing_elements). A recorded denial with no decoded
    letter still becomes a denial with no missing_elements — enough for the plan to
    route it to a Supplemental Claim. Factual organizing only; no outcome is asserted."""
    merged = list(denials)
    seen = {(d.get("name") or "").strip().lower() for d in merged}
    for c in conditions:
        if (c.get("va_status") or "").strip().lower() != "denied":
            continue
        lname = (c.get("name") or "").strip().lower()
        if not lname or lname in seen:
            continue
        seen.add(lname)
        merged.append({"name": c.get("name") or "", "missing_elements": []})
    return merged


def _is_existing(c: dict) -> bool:
    """A condition that already carries a rating (counts toward the baseline)."""
    r = c.get("current_rating")
    return isinstance(r, int) and r > 0


def _pursued_percent(c: dict) -> int | None:
    """The percent this condition would contribute if pursued on a pathway: the
    veteran's target rating (for a new claim or an increase). None when they haven't
    set one — we never invent a rating."""
    t = c.get("target_rating")
    return t if isinstance(t, int) and t > 0 else None


def _estimate(conditions: list[dict], pursued_ids: set) -> tuple[int | None, int]:
    """(estimated_combined, n_excluded). For conditions in `pursued_ids` use the
    target rating; for the rest use their existing current rating. Conditions with
    no usable percent are excluded from the number and counted so we can say so."""
    percents: list[int] = []
    excluded = 0
    for c in conditions:
        cid = c.get("id")
        if cid in pursued_ids:
            p = _pursued_percent(c)
            if p is None:
                # No target set. If the condition already carries a rating (e.g. a
                # ready increase claim), fall back to that current rating so the
                # estimate never reads lower than what already counts toward the
                # baseline. A brand-new claim with no rating at all stays excluded —
                # we never invent a percent.
                if _is_existing(c):
                    p = c["current_rating"]
                else:
                    excluded += 1
                    continue
        else:
            if not _is_existing(c):
                continue
            p = c["current_rating"]
        percents.append(p)
    if not percents:
        return None, excluded
    return combine(percents), excluded


def _basis(estimate: int | None, excluded: int) -> str:
    if estimate is None:
        return (
            "Set a target rating on your conditions (what you believe each should be "
            "rated) to see an estimated combined rating here. " + _NOT_A_PREDICTION
        )
    txt = (
        "Estimated with the §4.25 combined-ratings formula using the ratings you set "
        "(your current ratings plus your target ratings for the claims in this path), "
        "before VA's final rounding to the nearest 10%. " + _NOT_A_PREDICTION
    )
    if excluded:
        txt += (
            f" {excluded} condition(s) without a target rating you set aren't counted "
            "in this number."
        )
    return txt


def _first_missing(c: dict) -> str | None:
    missing = c.get("missing") or []
    return missing[0] if missing else None


_BAND_ORDER = {"complete": 0, "strong": 1, "building": 2, "early": 3}


def _condition_line(c: dict) -> dict:
    """Render one claimed condition for the Battle Plan's at-a-glance list. The
    `missing` entries are already the plain-English gap labels the readiness
    engine produced — passed through unchanged so the two pages never disagree."""
    band = c.get("band") or "early"
    missing = list(c.get("missing") or [])
    ct = c.get("claim_type") or "direct"
    return {
        "id": c.get("id"),
        "name": c.get("name") or "",
        "claim_type": _CLAIM_TYPE_LABELS.get(ct, ct.title()),
        "status": c.get("status") or "considering",
        "va_status": c.get("va_status") or "unknown",
        "band": band,
        "band_label": _BAND_LABELS.get(band, "In progress"),
        "ready": band in _READY_BANDS and not missing,
        "missing": missing,
        "current_rating": c["current_rating"] if isinstance(c.get("current_rating"), int) else None,
        "target_rating": c["target_rating"] if isinstance(c.get("target_rating"), int) else None,
        "link": f"/conditions/{c['id']}" if c.get("id") else "/conditions",
    }


def _process_roadmap(*, active_itf, ready, with_gaps, denials, has_filed) -> list[dict]:
    """The 'what to expect' claim-process journey, with each stop marked done /
    now / upcoming based on where THIS veteran actually is. Pure education — it
    describes VA's process, it does not predict an outcome."""

    def st(now: bool, done: bool = False) -> str:
        return "done" if done else ("now" if now else "upcoming")

    return [
        {
            "key": "itf",
            "title": "Lock in your date",
            "body": "File an Intent to File. It freezes your effective date — and any back "
            "pay if a claim is granted — for a full year while you get everything else ready.",
            "state": "done" if active_itf else st(bool(ready or with_gaps)),
        },
        {
            "key": "evidence",
            "title": "Build your evidence",
            "body": "Every claim needs three things: a current diagnosis, something in service "
            "that caused or worsened it, and a medical link (“nexus”) between them. "
            "Close the gaps on each condition until all three are in place.",
            "state": st(bool(with_gaps), done=bool(ready) and not with_gaps),
        },
        {
            "key": "file",
            "title": "File your claim",
            "body": "Submit the 21-526EZ — yourself on VA.gov or with a free VSO. You can "
            "file the conditions that are ready now and add the rest as they come together.",
            "state": st(bool(ready)),
        },
        {
            "key": "review",
            "title": "VA reviews it (and may order a C&P exam)",
            "body": "VA gathers your records and often schedules a Compensation & Pension exam. "
            "If yours comes up, prepare with the C&P companion and go — it carries real weight.",
            "state": st(bool(has_filed) and not denials),
        },
        {
            "key": "decision",
            "title": "Your decision arrives",
            "body": "VA mails a rating decision. Run it through the Decision decoder here so you "
            "understand exactly what was granted, what was denied, and why.",
            "state": "done" if denials else "upcoming",
        },
        {
            "key": "appeal",
            "title": "Not done? You can appeal",
            "body": "A denial is not the end of the road. Most veterans file a Supplemental Claim "
            "with new evidence — you have a year to keep your original effective date. The "
            "Appeals tool drafts it with you.",
            "state": st(bool(denials)),
        },
    ]


def build_game_plan(
    *,
    conditions: list[dict],
    denials: list[dict],
    suggestions: list[dict],
    active_itf: dict | None,
    current_combined: int | None,
    generated_at: str,
) -> dict:
    """Assemble the GamePlanOut payload.

    conditions: [{id, name, claim_type, status, current_rating, target_rating,
                  band, missing:[label], has_have_evidence:bool}]
    denials:    [{name, missing_elements:[token]}]  (from decoded letters)
    suggestions:[{name, relation, kind:"secondary"|"presumptive"}]  (not-yet-claimed)
    active_itf: {type, deadline, days_remaining} | None
    """
    # Conditions the veteran/VA recorded as denied are denials too — merge them into
    # whatever the decoded letters produced (deduped by name) before building anything.
    denials = merge_denied_conditions(denials, conditions)
    has_conditions = bool(conditions)
    # Already-granted conditions (VA service-connected, not an increase claim) are
    # never "claimable" — filing them again is re-filing a settled grant. Excluding
    # them here keeps them out of "file now", the ready count, and the file actions,
    # which is what fixes "Ready to file" showing for conditions VA already approved.
    claimable = [
        c for c in conditions
        if c.get("status") not in ("filed", "decided") and not is_already_granted(c)
    ]
    ready = [c for c in claimable if c.get("band") in _READY_BANDS]
    with_gaps = [c for c in claimable if c.get("missing")]
    cond_by_lname = {(c.get("name") or "").strip().lower(): c for c in conditions}

    # ── Snapshot ────────────────────────────────────────────────────────────
    snapshot = {
        "current_combined": current_combined,
        "conditions_total": len(conditions),
        "ready_count": len(ready),
        "needs_evidence_count": len(with_gaps),
        "denied_count": len(denials),
        "active_itf": active_itf,
    }

    # ── Pathways ────────────────────────────────────────────────────────────
    pathways: list[dict] = []

    if ready:
        ids = {c["id"] for c in ready}
        est, exc = _estimate(conditions, ids)
        steps = []
        if not active_itf:
            steps.append(
                "File an Intent to File first — it locks in your effective date (and "
                "back pay) for a year, even before the full claim."
            )
        steps.append(
            "Assemble your 21-526EZ for the conditions whose core evidence is already "
            "in place: " + ", ".join(c["name"] for c in ready) + "."
        )
        steps.append("File it yourself at VA.gov, or hand it to a free VSO.")
        steps.append(
            "Keep gathering evidence for your remaining conditions and add them when "
            "they're ready."
        )
        pathways.append({
            "key": "file_now",
            "title": "File what's ready now",
            "summary": (
                "Move on the conditions whose core evidence you've already identified. "
                "The sooner you file (or file an Intent to File), the sooner you can "
                "protect your effective date — and any back pay if the claim is granted."
            ),
            "steps": steps,
            "included_conditions": [c["name"] for c in ready],
            "estimated_combined": est,
            "estimated_combined_basis": _basis(est, exc),
            "tradeoff": (
                "Fastest, and it protects your effective date. You can file the rest "
                "later or add them to this claim as evidence comes together."
            ),
            "recommended": False,
        })

    if with_gaps:
        ids = {c["id"] for c in claimable}
        est, exc = _estimate(conditions, ids)
        steps = []
        for c in with_gaps[:5]:
            gap = _first_missing(c)
            if gap:
                steps.append(f"Close the gap on {c['name']}: {gap}.")
        steps.append("Then file the strongest version of your claim — all at once.")
        pathways.append({
            "key": "strengthen_first",
            "title": "Close the key gaps, then file",
            "summary": (
                "Spend a little longer gathering the missing pieces so each claim is as "
                "strong as it can be before VA sees it. Best when you're not up against "
                "a deadline."
            ),
            "steps": steps,
            "included_conditions": [c["name"] for c in claimable],
            "estimated_combined": est,
            "estimated_combined_basis": _basis(est, exc),
            "tradeoff": (
                "Slower to file, but every claim goes in with its core evidence in "
                "place. Pair it with an Intent to File so waiting doesn't cost you back "
                "pay."
            ),
            "recommended": False,
        })

    if suggestions:
        ids = {c["id"] for c in claimable}
        est, exc = _estimate(conditions, ids)
        steps = [
            f"Look into {s['name']} — {s['relation']}."
            for s in suggestions[:6]
        ]
        steps.append(
            "Add any that fit as new conditions, then gather evidence for them like any "
            "other claim."
        )
        pathways.append({
            "key": "add_conditions",
            "title": "Explore conditions you may be missing",
            "summary": (
                "Based on what you've already claimed and your service, these related "
                "conditions are commonly connected and worth checking — secondaries and "
                "presumptives veterans often overlook."
            ),
            "steps": steps,
            "included_conditions": [s["name"] for s in suggestions],
            "estimated_combined": est,
            "estimated_combined_basis": (
                _basis(est, exc)
                + f" {len(suggestions)} suggested condition(s) aren't in this number "
                "until you add them and set a target rating."
            ),
            "tradeoff": (
                "More conditions can mean a higher combined rating, but each still needs "
                "its own evidence. Explore them; don't file anything you can't support."
            ),
            "recommended": False,
        })

    if denials:
        steps = []
        for d in denials:
            plains = [_MISSING_PLAIN.get(e, e) for e in (d.get("missing_elements") or [])]
            reason = (
                " the denial pointed to a missing " + " and ".join(plains)
                if plains
                else " review the decision for the reason given"
            )
            steps.append(
                f"{d['name']}:{reason}. A Supplemental Claim (VA Form 20-0995) with new, "
                "relevant evidence is the usual next step."
            )
        pathways.append({
            "key": "appeal_denials",
            "title": "Respond to your denials",
            "summary": (
                "You have decisions that denied one or more conditions. The right lane "
                "depends on why — most often a Supplemental Claim with new evidence. The "
                "Appeals tool drafts your response."
            ),
            "steps": steps,
            "included_conditions": [d["name"] for d in denials],
            "estimated_combined": None,
            "estimated_combined_basis": (
                "No estimate here — an appeal's outcome depends entirely on the new "
                "evidence and VA's review. " + _NOT_A_PREDICTION
            ),
            "tradeoff": (
                "Filing within one year of the decision preserves your original "
                "effective date. A VSO can help you pick the right lane."
            ),
            "recommended": False,
        })

    # Fallback: conditions exist but they're all already filed/decided (nothing to
    # file, strengthen, add, or appeal) — give the veteran the "now you wait" plan
    # instead of an empty page.
    if has_conditions and not pathways:
        pathways.append({
            "key": "track_progress",
            "title": "Track your filed claims",
            "summary": (
                "Your conditions are already with VA. The active work now is watching "
                "each claim and responding quickly to anything VA asks for."
            ),
            "steps": [
                "Check each claim's status on VA.gov (or the Claims page here).",
                "If VA schedules a C&P exam, prepare with the C&P companion and go.",
                "When a decision arrives, run it through the Decision decoder — and use "
                "Appeals if anything was denied.",
            ],
            "included_conditions": [c["name"] for c in conditions],
            "estimated_combined": None,
            "estimated_combined_basis": (
                "No estimate here — your claims are already with VA. " + _NOT_A_PREDICTION
            ),
            "tradeoff": (
                "Nothing to file right now; stay responsive to VA's requests so nothing "
                "stalls."
            ),
            "recommended": False,
        })

    # Recommend exactly one: protect the effective date first (file now), else
    # strengthen, else appeal, else the first available.
    if pathways:
        order = ["file_now", "strengthen_first", "appeal_denials", "add_conditions"]
        by_key = {p["key"]: p for p in pathways}
        for key in order:
            if key in by_key:
                by_key[key]["recommended"] = True
                break
        else:
            pathways[0]["recommended"] = True

    # Under-claimed opportunities (computed once, reused for actions + payload):
    # newly-establishable §3.310 SECONDARY theories (e.g. depression/anxiety secondary
    # to a service-connected chronic illness, even if denied on a direct basis before)
    # + Esteban-positive separate ratings the veteran may be under-rated for.
    opportunities = opportunities_for(conditions)

    # ── Priority actions (ranked high→low, capped) ──────────────────────────
    actions: list[dict] = []

    if not active_itf and claimable:
        actions.append({
            "title": "File an Intent to File today",
            "why": (
                "It can lock in your effective date — and any back pay if a claim is "
                "granted — for a year while you gather evidence, even before your full "
                "claim."
            ),
            "category": "protect_backpay",
            "condition_name": None,
            "impact": "high",
            "link": "/itf",
        })

    # High-severity reclaim / secondary opportunities FIRST (before a long list of
    # generic Supplemental-Claim denials crowds them out of the top 12).
    for o in [op for op in opportunities if op.get("severity") == "high"][:4]:
        is_reclaim = o.get("kind") == "reclaim"
        primary0 = (o.get("primary") or [""])[0] or ""
        secondary_name = o.get("secondary") or ""
        if is_reclaim:
            nexus_q = urlencode(
                {
                    "condition": secondary_name,
                    "claim_type": "secondary",
                    "secondary_to": primary0,
                    "brief": "1",
                    "prior_denial": "1",
                }
            )
            nexus_link = f"/nexus?{nexus_q}"
        else:
            nexus_link = "/secondaries"
        actions.append({
            "title": (
                f"Reclaim {secondary_name} (new secondary basis)"
                if is_reclaim else
                f"Re-approach {secondary_name} as secondary"
            ),
            "why": (
                f"It may be establishable as secondary to your {primary0} — a new "
                "theory of entitlement that can support a Supplemental Claim"
                + (" with new and relevant evidence." if is_reclaim else ".")
            ),
            "category": "reclaim" if is_reclaim else "add_condition",
            "condition_name": secondary_name,
            "impact": "high" if is_reclaim else "medium",
            "link": nexus_link,
        })

    # TDIU workspace when the §4.16 screen fired (near or at threshold).
    tdiu_early = screen_tdiu(conditions, current_combined)
    if tdiu_early:
        actions.append({
            "title": (
                "Build your TDIU work-history record"
                if tdiu_early.get("eligible_schedular")
                else "Review TDIU — you may be near the threshold"
            ),
            "why": (
                "TDIU turns on substantially gainful employment and your work chronology "
                "(21-8940 / employer statements) — not just more diagnoses. Organize the "
                "record with a VSO; this is education, not a determination."
            ),
            "category": "protect_backpay",
            "condition_name": None,
            "impact": "high" if tdiu_early.get("eligible_schedular") else "medium",
            "link": "/tdiu",
        })

    # Cap denial-driven Supplemental actions so they don't bury reclaim/nexus work.
    for d in denials[:5]:
        c = cond_by_lname.get((d.get("name") or "").strip().lower())
        has_ev = bool(c and c.get("has_have_evidence"))
        plains = [_MISSING_PLAIN.get(e, e) for e in (d.get("missing_elements") or [])]
        why = (
            "VA denied this for a missing " + " and ".join(plains) + "; a Supplemental "
            "Claim adds new, relevant evidence."
            if plains
            else "A Supplemental Claim adds new, relevant evidence for a denied condition."
        )
        actions.append({
            "title": f"Start a Supplemental Claim for {d['name']}",
            "why": why,
            "category": "appeal",
            "condition_name": d["name"],
            "impact": "high" if has_ev else "medium",
            "link": "/appeals",
        })

    for c in with_gaps:
        gap = _first_missing(c)
        if not gap:
            continue
        actions.append({
            "title": f"Get {gap.lower()} for {c['name']}",
            "why": f"It's a core piece VA needs to connect {c['name']} to your service.",
            "category": "close_gap",
            "condition_name": c["name"],
            "impact": "high" if c.get("band") == "early" else "medium",
            "link": f"/conditions/{c['id']}" if c.get("id") else "/conditions",
        })

    for c in ready:
        actions.append({
            "title": f"File your claim for {c['name']}",
            "why": "Its core evidence is in place — filing protects your effective date.",
            "category": "file",
            "condition_name": c["name"],
            "impact": "high",
            "link": "/application",
        })

    for s in suggestions[:4]:
        actions.append({
            "title": f"Explore {s['name']}",
            "why": f"{s['relation']} — a commonly linked condition worth checking.",
            "category": "add_condition",
            "condition_name": s["name"],
            "impact": "medium",
            "link": "/presumptives" if s.get("kind") == "presumptive" else "/secondaries",
        })

    # All conditions filed/decided → no actionable step above; give the veteran the
    # one thing left to do rather than an empty list.
    if has_conditions and not actions:
        actions.append({
            "title": "Check your claim status",
            "why": (
                "Your claims are in with VA — track each one and respond quickly to any "
                "request so nothing stalls."
            ),
            "category": "track",
            "condition_name": None,
            "impact": "medium",
            "link": "/claims",
        })

    # Dedup identical actions (e.g. two conditions with the same name) before the cap,
    # then keep the highest-impact 12 (stable sort preserves insertion order within a
    # tier, so the drops are always the lowest-impact tail).
    seen_actions: set = set()
    deduped: list[dict] = []
    for a in actions:
        key = (a["title"], a["category"], a.get("condition_name"))
        if key in seen_actions:
            continue
        seen_actions.add(key)
        deduped.append(a)
    deduped.sort(
        key=lambda a: (_IMPACT_RANK.get(a["impact"], 1), _CATEGORY_RANK.get(a["category"], 9))
    )
    actions = deduped[:12]

    # ── Focus: the single most important next thing (top-ranked action) ──────
    focus = None
    if actions:
        a0 = actions[0]
        focus = {"title": a0["title"], "why": a0["why"], "link": a0.get("link")}

    # ── At-a-glance condition list (all conditions, most-ready first) ─────────
    condition_lines = sorted(
        (_condition_line(c) for c in conditions),
        key=lambda l: _BAND_ORDER.get(l["band"], 3),
    )

    # ── Rating-strategy cautions ("poking the bear": §4.14 pyramiding, §4.130
    # one mental rating, §3.344/§3.951 reduction, CFS/fibro trade-offs, TDIU
    # employment risk) + the TDIU screen (§4.16). Educational and reg-grounded —
    # they surface trade-offs, never a bar or a prediction. Computed over ALL
    # conditions (granted included) so overlaps and reduction risk against
    # settled ratings are visible. TDIU is screened first so employment caution
    # can attach when the schedular door is near/open. ──────────────────────────
    tdiu = screen_tdiu(conditions, current_combined)
    cautions = cautions_for(conditions, tdiu=tdiu)

    # ── What-to-expect roadmap, personalized to where they are ───────────────
    has_filed = any(c.get("status") in ("filed", "decided") for c in conditions)
    process_roadmap = _process_roadmap(
        active_itf=active_itf,
        ready=ready,
        with_gaps=with_gaps,
        denials=denials,
        has_filed=has_filed,
    )

    return {
        "generated_at": generated_at,
        "snapshot": snapshot,
        "pathways": pathways,
        "priority_actions": actions,
        "has_conditions": has_conditions,
        "disclaimer": _DISCLAIMER,
        "vso_referral": _VSO_REFERRAL,
        "source_note": _SOURCE_NOTE,
        "condition_lines": condition_lines,
        "process_roadmap": process_roadmap,
        "focus": focus,
        "cautions": cautions,
        "tdiu": tdiu,
        "opportunities": opportunities,
    }

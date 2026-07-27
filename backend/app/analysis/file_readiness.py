"""File-readiness DELTA — the plain answer to "what do I still need to file?"

Deterministic, no AI. Aggregates the per-condition gap engine (analysis/gaps.py) into
one prioritized to-do list: what's still missing, why it matters, which conditions need
it, and where in the app to go fix it. Surfaced prominently (Dashboard / Battle Plan) so
the veteran always knows the delta between where they are and a filable claim.

Also returns a 0–100 score, a slim blockers list, and static handoff links so the
veteran can take the packet to VA.gov or a free VSO — we never e-file for them.
"""

from __future__ import annotations

from .gaps import analyze_gaps

# gap.kind → where to go fix it + the plain next step. Kinds come from analysis/gaps.py.
_GAP_ACTION: dict[str, tuple[str, str]] = {
    "diagnosis": ("/documents", "Upload recent treatment records that show the diagnosis"),
    "service_record": ("/documents", "Add service treatment or personnel records — or a buddy statement about the event"),
    "nexus_letter": ("/nexus", "Get a medical nexus opinion, or a completed DBQ, linking it to service"),
    "dbq": ("/nexus", "Have a provider complete the DBQ for this condition"),
    "continuity": ("/symptom-log", "Log your ongoing symptoms over time — or add a lay statement"),
    "lay_statement": ("/statement", "Write a personal statement describing the event and its effects"),
    "primary_link": ("/conditions", "Link this to the service-connected condition it stems from"),
    "treatment_record": ("/documents", "Upload treatment records for this condition"),
}
_DEFAULT_ACTION = ("/evidence", "Add this evidence")

# Static handoff destinations — pro-se self-help only. Rating Raider prepares the
# packet; the veteran (or a free accredited VSO) files it. Never e-file as the veteran.
HANDOFF = {
    "va_gov_claim_url": "https://www.va.gov/disability/how-to-file-claim/",
    "vso_url": "https://www.va.gov/get-help-from-accredited-representative/",
    "itf_url": "https://www.va.gov/resources/your-intent-to-file-a-va-claim/",
    "form526_route": "/application",
    "packet_note": (
        "Rating Raider prepares review-and-sign drafts only — you file at VA.gov or "
        "with a free VSO. We never e-file for you."
    ),
}


def _action(kind: str) -> tuple[str, str]:
    return _GAP_ACTION.get(kind, _DEFAULT_ACTION)


def assemble_file_readiness(
    conditions: list[dict],
    ev_by_cond: dict,
    profile: dict | None,
    max_ratings: dict | None,
) -> dict:
    """Fold every condition's gaps into one delta.

    `conditions`  — [{id, name, claim_type, secondary_to, in_service_event, nexus_notes,
                     diagnostic_code, current_rating}] (mirrors readiness.py's shape).
    `ev_by_cond`  — {condition_id(str): [{kind, status}]}.
    Returns: overall ready flag + counts, a de-duplicated prioritized 'still needed'
    list (each with the conditions that need it + where to fix it), a per-condition
    ready/gaps breakdown, a 0–100 score, slim blockers, and static handoff links.
    Purely deterministic — safe to compute on every page load.
    """
    per_condition: list[dict] = []
    # Group identical gaps across conditions so the veteran sees "Medical nexus opinion
    # — needed for X and Y" once, not twice.
    needed: dict[str, dict] = {}
    ready_count = 0

    for cond in conditions:
        cid = str(cond.get("id"))
        gaps = analyze_gaps(cond, ev_by_cond.get(cid, []), profile, max_ratings=max_ratings)
        # Informational items (e.g. "at schedular maximum") aren't blockers to filing.
        cond_blockers = [g for g in gaps if "schedular maximum" not in (g.get("label") or "").lower()]
        name = cond.get("name") or "this condition"
        is_ready = len(cond_blockers) == 0
        if is_ready:
            ready_count += 1
        per_condition.append(
            {
                "condition_id": cid,
                "name": name,
                "ready": is_ready,
                "still_needs": [g.get("label") for g in cond_blockers if g.get("label")],
            }
        )
        for g in cond_blockers:
            label = g.get("label") or ""
            if not label:
                continue
            route, how = _action(g.get("kind") or "")
            entry = needed.setdefault(
                label,
                {
                    "label": label,
                    "detail": g.get("detail") or "",
                    "how": how,
                    "route": route,
                    "kind": g.get("kind") or "",
                    "conditions": [],
                },
            )
            if name not in entry["conditions"]:
                entry["conditions"].append(name)

    # Prioritize: the elements that block the MOST claims first, then diagnosis/nexus
    # (the load-bearing ones) ahead of secondary items.
    _PRIORITY = {"diagnosis": 0, "nexus_letter": 1, "service_record": 2}
    still_needed = sorted(
        needed.values(),
        key=lambda e: (-len(e["conditions"]), _PRIORITY.get(e["kind"], 9), e["label"]),
    )

    total = len(conditions)
    # Score is the share of conditions whose core evidence is identified (0 when none).
    file_ready_score = int(round((ready_count / total) * 100)) if total > 0 else 0
    blockers = [
        {"label": n["label"], "route": n["route"], "how": n["how"]}
        for n in still_needed
    ]
    return {
        "total_conditions": total,
        "ready_conditions": ready_count,
        "all_ready": total > 0 and ready_count == total,
        "has_conditions": total > 0,
        "still_needed": still_needed,
        "per_condition": per_condition,
        "file_ready_score": file_ready_score,
        "blockers": blockers,
        "handoff": dict(HANDOFF),
    }

"""Assemble a records-correction application packet — PURE (no DB, no clock).

Routes the situation (route.py), then builds a print-ready packet: a drafted
statement of the error or injustice (the veteran's own words VERBATIM plus a
structured frame), a tailored evidence checklist, filing instructions, and an
attestation. Educational — the veteran reviews, signs, and files it with the board;
Rating Raider never files and never renders a legal opinion.
"""

from __future__ import annotations

from .route import route_correction

_ATTESTATION = (
    "I certify that the statements in this application are true and complete to the "
    "best of my knowledge and belief. I understand this application is submitted by me "
    "for my own review and signature."
)

_SOURCE_NOTE = (
    "Assembled from what you entered. This is a working draft to review and sign — it "
    "is not the official filing, and nothing is sent to the board by Rating Raider. "
    "File it yourself, or with a free VSO or veterans legal clinic."
)


def _evidence_checklist(situation: dict, route: dict) -> list[dict]:
    """Tailor the supporting-evidence list to the board + what's being corrected."""
    goals = set(situation.get("goals") or [])
    related = set(situation.get("related_to") or [])
    board = route.get("board")
    items: list[dict] = [
        {
            "item": "A copy of your DD-214 (and any DD-215)",
            "why": "The board needs to see the record you're asking it to correct.",
        },
        {
            "item": "Your military personnel records (request them from the NPRC / your service if you don't have them)",
            "why": "They show what actually happened and support your account.",
        },
    ]

    if goals & {"discharge_upgrade", "narrative_reason", "re_code"}:
        items.append({
            "item": "Any records about the events behind your discharge",
            "why": "Counseling statements, incident reports, medical records — whatever bears on why you were separated.",
        })
        items.append({
            "item": "Character references and buddy statements",
            "why": "People who served with you, and post-service references, can speak to who you are and to the injustice.",
        })
        items.append({
            "item": "Evidence of post-service conduct (work, school, treatment, community)",
            "why": "Boards weigh your whole record, including rehabilitation and good conduct since service.",
        })

    if related:
        items.append({
            "item": "Medical or mental-health records, or a current diagnosis (VA or private)",
            "why": "They connect PTSD/TBI/mental-health/MST to what happened — the core of a liberal-consideration request.",
        })
        if "mst" in related:
            items.append({
                "item": "Any markers of the MST (even indirect)",
                "why": "Reports are often absent, which is expected — statements, changes in behavior, requests for transfer, or a later diagnosis can all serve as markers.",
            })

    if board == "PDBR":
        items.append({
            "item": "Your MEB/PEB findings and service treatment records",
            "why": "The PDBR re-reviews the disability rating built on these records.",
        })
        items.append({
            "item": "Any VA rating decision for the same conditions",
            "why": "A higher VA rating for the same condition supports raising the DoD rating.",
        })

    if "records_error" in goals:
        items.append({
            "item": "Documentary proof of the correct fact (orders, award citations, official records)",
            "why": "A clerical fix (name, date, award, rank) is strongest with the source document that proves it.",
        })

    return items


def _instructions(route: dict) -> list[str]:
    form = route.get("form") or "the correct DD form"
    board_full = route.get("board_full") or "the board"
    return [
        f"Complete {form} ({route.get('form_title', '')}) — download the current version "
        "from the DoD forms site (esd.whs.mil) or your service board's page.",
        "Attach this statement of error or injustice and the evidence you gathered.",
        f"Submit it to {board_full}. Most boards accept applications online; check your "
        "service board's website for the current portal or mailing address.",
        "Keep a complete copy of everything you send, and note the date you filed.",
        "If a board grants relief, it issues a DD Form 215 (or a reissued DD-214) — then "
        "send the corrected DD-214/DD-215 to VA for any benefits the change affects.",
    ]


def _statement(situation: dict, route: dict, requested: list[dict], veteran_statement: str | None) -> str:
    """Draft the statement of error or injustice: a structured frame + the veteran's
    verbatim words. The app never asserts a legal conclusion — it organizes what the
    veteran says."""
    lines: list[str] = ["STATEMENT OF ERROR OR INJUSTICE", ""]
    if requested:
        lines.append("I am asking the board to correct the following in my record:")
        for r in requested:
            field = (r.get("field") or "").strip() or "(item)"
            cur = (r.get("current") or "").strip()
            req = (r.get("requested") or "").strip()
            piece = f"  • {field}"
            if cur:
                piece += f" — currently: {cur}"
            if req:
                piece += f" — should be: {req}"
            lines.append(piece)
        lines.append("")

    if route.get("liberal_consideration", {}).get("applies"):
        lines.append(
            "I request that the board apply liberal consideration to this application "
            "under the Hagel, Carson, Kurta, and Wilkie memoranda. I believe my discharge "
            "was connected to a condition (PTSD, TBI, another mental-health condition, or "
            "military sexual trauma) that was not adequately recognized at the time."
        )
        lines.append("")

    lines.append("In my own words:")
    lines.append((veteran_statement or "").strip() or "[Write, in your own words, what is wrong or unjust and why. Be specific and factual.]")
    return "\n".join(lines)


def build_correction_packet(
    *, payload: dict, prepared_on: str | None = None
) -> dict:
    """payload: {situation, applicant_name?, corrections_requested[], veteran_statement?}."""
    situation = payload.get("situation") or {}
    route = route_correction(situation)
    requested = payload.get("corrections_requested") or []
    veteran_statement = payload.get("veteran_statement")

    board_full = route.get("board_full") or "the correction board"
    heading = f"Application to {board_full}"

    return {
        "route": route,
        "prepared_on": prepared_on,
        "heading": heading,
        "applicant_name": payload.get("applicant_name"),
        "corrections_requested": requested,
        "statement_of_error_or_injustice": _statement(situation, route, requested, veteran_statement),
        "veteran_statement": veteran_statement,
        "evidence_checklist": _evidence_checklist(situation, route),
        "instructions": _instructions(route),
        "attestation": _ATTESTATION,
        "signature_block": "Signature: ______________________________    Date: ______________",
        "vso_referral": route["vso_referral"],
        "legal_aid_referral": route["legal_aid_referral"],
        "disclaimer": route["disclaimer"],
        "source_note": _SOURCE_NOTE,
    }

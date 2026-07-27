"""Appeals draft-assist assembly — PURE (no DB, no LLM, no clock).

`build_candidates(...)` turns already-read data (decoded letters + claimed
conditions + have-status evidence) into the `AppealCandidatesOut` shape.
`build_appeal_draft(payload, today, prepared_on)` assembles the print-ready
`AppealDraftOut` — plain-English of each missing element, the veteran's chosen
new-and-relevant evidence, and the veteran's statement VERBATIM.

Reuses the decoder's building blocks so the appeals lane copy and the appeal
window are identical to what the decoder already shows: `decoder.deadline.
appeal_window` (the 1-year AMA window) and `decoder.analyze` (the three AMA lanes,
the VSO referral). Nothing here files, advises, or opines — it never rewrites the
veteran's words and never asserts a medical link; it only frames the lane against
the element VA said was missing.
"""

from __future__ import annotations

from datetime import date

from ..decoder import analyze
from ..decoder.deadline import appeal_window

# Plain-English of each §3.303 element VA can find "missing" in a denial. The
# same three-element vocabulary the whole app uses.
_MISSING_PLAIN = {
    "current_disability": (
        "a current, diagnosed disability (a doctor's diagnosis today)"
    ),
    "in_service_event": (
        "an in-service event, injury, exposure, or illness in your service records"
    ),
    "nexus": (
        'a medical link ("nexus") connecting your current diagnosis to your service'
    ),
}

_LANE_META = {
    "supplemental_claim": {
        "title": "Supplemental Claim (VA Form 20-0995)",
        "form": "20-0995",
    },
    "higher_level_review": {
        "title": "Higher-Level Review (VA Form 20-0996)",
        "form": "20-0996",
    },
    "board_appeal": {
        "title": "Board Appeal (VA Form 10182)",
        "form": "10182",
    },
}

# Lane-aware framing — the veteran's first-person intent, in the shape of the
# lane. This is educational template copy (like the buddy/nexus/statement
# builders), NOT the veteran's verbatim words and NOT a medical opinion.
_LANE_INTRO = {
    "supplemental_claim": (
        "I am filing a Supplemental Claim (VA Form 20-0995) on the decision below. "
        "I am submitting NEW and RELEVANT evidence that a reviewer has not "
        "previously considered. I understand that filing this Supplemental Claim "
        "within one year of the decision date preserves my original effective date."
    ),
    "higher_level_review": (
        "I am requesting a Higher-Level Review (VA Form 20-0996) of the decision "
        "below. I am NOT submitting new evidence — I am asking a senior reviewer to "
        "re-examine the same record already on file for an error in how the "
        "existing evidence and rules were applied. I understand I may request an "
        "informal conference to explain where I believe VA went wrong."
    ),
    "board_appeal": (
        "I am filing a Board Appeal (VA Form 10182) of the decision below to the "
        "Board of Veterans' Appeals for review by a Veterans Law Judge. I "
        "understand I may choose the direct-review docket (no new evidence), the "
        "evidence-submission docket, or a hearing docket."
    ),
}

_VETERAN_ATTESTATION = (
    "I certify that the statements above are true and correct to the best of my "
    "knowledge and belief. I understand this response is not filed until I review "
    "it, sign it, and submit it to VA myself — or a VA-accredited representative "
    "submits it on my behalf. Rating Raider has not filed anything for me."
)

_SIGNATURE_BLOCK = (
    "Veteran signature: __________________________________   Date: ______________\n"
    "Printed name: ______________________________________\n"
    "VA file number / Social Security number: ___________________________________"
)

_DRAFT_DISCLAIMER = (
    "Veteran-Ops is self-help educational software — not legal advice, not a "
    "VA-accredited representative, and not affiliated with VA. This is a DRAFT "
    "decision-review response prepared for YOUR review and signature; Rating Raider "
    "does not file or appeal anything for you and never renders a medical opinion. "
    "Your own words above are reproduced exactly as you wrote them. Free help "
    "appealing a VA decision is available from a VA-accredited VSO (VFW, DAV, The "
    "American Legion, or your state/county veterans office) — you never have to pay "
    "to appeal a VA decision."
)

_CANDIDATES_DISCLAIMER = (
    "These are conditions you could supplement or appeal, drawn from your decoded "
    "decision letters and your claimed conditions. This is educational only — Rating "
    "Raider is not a VA-accredited representative and does not appeal anything for "
    "you, and it never renders a medical opinion. A free VSO can help you decide "
    "whether and how to respond."
)


def _draft_source_note(form: str) -> str:
    return (
        "Assembled from the contentions and evidence you selected and the statement "
        f"you wrote. Transcribe this onto the official VA form ({form}) and file it "
        "at VA.gov, or hand it to a free VSO. VA's decision letter itself controls — "
        "confirm deadlines and your options with a VSO."
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _join(items: list[str]) -> str:
    """A readable inline list: 'a', 'a and b', 'a, b, and c'."""
    parts = [i for i in items if i]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _what_this_addresses(lane: str, missing_plain: list[str]) -> str:
    """One sentence tying the chosen lane to the missing element(s). Frames the
    lane; it never asserts the medical link itself (no opinion)."""
    if missing_plain:
        gap = (
            f"the missing element{'s' if len(missing_plain) > 1 else ''} VA "
            f"identified — {_join(missing_plain)}"
        )
    else:
        gap = "the concerns VA raised in this decision"
    if lane == "higher_level_review":
        return (
            "This Higher-Level Review asks a senior reviewer to re-examine the "
            f"record already on file, focusing on {gap}."
        )
    if lane == "board_appeal":
        return (
            "This Board Appeal asks a Veterans Law Judge to review the decision, "
            f"focusing on {gap}."
        )
    return (
        "This Supplemental Claim submits new and relevant evidence aimed at "
        f"{gap}."
    )


def _match_evidence(
    candidate_name: str,
    candidate_condition_id: str | None,
    have_evidence: list[dict],
) -> list[dict]:
    """The veteran's have-status evidence whose condition matches this candidate
    by condition_id or by condition NAME (case-insensitive) — the "new and
    relevant" material a Supplemental Claim needs. `AppealEvidenceRef` shape."""
    name_l = (candidate_name or "").strip().lower()
    refs: list[dict] = []
    for e in have_evidence:
        cid = e.get("condition_id")
        cname = (e.get("condition_name") or "").strip().lower()
        by_id = bool(candidate_condition_id) and str(cid) == str(candidate_condition_id)
        by_name = bool(name_l) and cname == name_l
        if by_id or by_name:
            refs.append({"kind": e.get("kind") or "other", "title": e.get("title") or ""})
    return refs


def build_candidates(
    *,
    decoded_docs: list[dict],
    conditions: list[dict],
    have_evidence: list[dict],
    today: date,
) -> dict:
    """Compose the `AppealCandidatesOut` payload from plain, already-read data.

    decoded_docs:  [{document_id: str, decode: <cached DecodeOut dict>}] — one
                   candidate per DENIED decision row (appeal_window recomputed).
    conditions:    [{condition_id: str, name: str, diagnostic_code: str|None}] —
                   one candidate each (decision=None, missing_elements=[]).
    have_evidence: [{condition_id, condition_name, kind, title}] — status=='have'.
    today:         passed in (pure) — the reference date for the appeal window.
    """
    candidates: list[dict] = []

    for doc in decoded_docs:
        document_id = str(doc["document_id"])
        decode = doc.get("decode") or {}
        decision_date = decode.get("decision_date")
        dd = _parse_date(decision_date)
        for row in decode.get("decisions") or []:
            if row.get("decision") != "denied":
                continue
            name = row.get("name") or "This condition"
            candidates.append(
                {
                    "source": "decoded_letter",
                    "name": name,
                    "diagnostic_code": row.get("diagnostic_code"),
                    "decision": "denied",
                    "missing_elements": list(row.get("missing_elements") or []),
                    "document_id": document_id,
                    "condition_id": None,
                    "decision_date": decision_date,
                    "appeal_window": appeal_window(dd, today),
                    "new_evidence": _match_evidence(name, None, have_evidence),
                }
            )

    for cond in conditions:
        cid = str(cond["condition_id"])
        name = cond.get("name") or ""
        candidates.append(
            {
                "source": "condition",
                "name": name,
                "diagnostic_code": cond.get("diagnostic_code"),
                "decision": None,
                "missing_elements": [],
                "document_id": None,
                "condition_id": cid,
                "decision_date": None,
                "appeal_window": None,
                "new_evidence": _match_evidence(name, cid, have_evidence),
            }
        )

    return {
        "candidates": candidates,
        "lanes": analyze._lanes(analyze._DEFAULT_REVIEW_SOURCE),
        "vso_referral": analyze._VSO_REFERRAL,
        "disclaimer": _CANDIDATES_DISCLAIMER,
    }


def build_appeal_draft(payload, today: date, prepared_on: str | None) -> dict:
    """Compose the `AppealDraftOut` payload — PURE.

    payload:      the validated `AppealDraftIn` (>=1 contention).
    today:        passed in (pure) — the reference date for the appeal deadline.
    prepared_on:  the router-stamped ISO date string (pure funcs can't read the
                  clock).
    """
    lane = payload.lane
    meta = _LANE_META.get(lane, _LANE_META["supplemental_claim"])

    contentions_out: list[dict] = []
    for c in payload.contentions:
        missing_plain = [
            _MISSING_PLAIN[m] for m in (c.missing_elements or []) if m in _MISSING_PLAIN
        ]
        contentions_out.append(
            {
                "name": c.name,
                "diagnostic_code": c.diagnostic_code,
                "missing_element_plain": missing_plain,
                # Echo the veteran's chosen "new and relevant" evidence titles.
                "new_and_relevant_evidence": list(c.new_evidence_titles or []),
                # VERBATIM — the veteran's own words, never rewritten or paraphrased.
                "veteran_statement": c.veteran_statement,
                "what_this_addresses": _what_this_addresses(lane, missing_plain),
            }
        )

    dd = _parse_date(payload.decision_date)

    return {
        "lane_key": lane,
        "lane_title": meta["title"],
        "lane_form": meta["form"],
        "prepared_on": prepared_on,
        "heading": f"{meta['title']} — response prepared for your review and signature",
        "intro": _LANE_INTRO.get(lane, _LANE_INTRO["supplemental_claim"]),
        "contentions": contentions_out,
        "deadline": appeal_window(dd, today),
        "lane_guidance": analyze._lanes(analyze._DEFAULT_REVIEW_SOURCE),
        "veteran_attestation": _VETERAN_ATTESTATION,
        "signature_block": _SIGNATURE_BLOCK,
        "vso_referral": analyze._VSO_REFERRAL,
        "disclaimer": _DRAFT_DISCLAIMER,
        "source_note": _draft_source_note(meta["form"]),
    }

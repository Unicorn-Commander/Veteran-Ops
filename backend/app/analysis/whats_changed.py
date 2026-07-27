"""'What's changed since you were rated' — compare a veteran's rating date against
dated VA regulatory changes and surface the ones that may now help THEM.

Split by design (Aaron's two rules):
  * DETERMINISTIC CORE (no AI) — rating-date derivation + change matching + an action
    signal. Generic facts (what each change IS, its date, its source) come from the
    curated regulatory_changes.py, never from a model.
  * PERSON-SPECIFIC judgment (assess_actionability) — the ONLY AI step: given THIS
    veteran's condition + evidence, is there enough to act, and what's the gap? Local
    Qwen first; escalation-ready via the model arg (the gateway allowlist gates it).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.gateway import gateway
from ..models import ClaimedCondition, Document, VeteranProfile
from . import regulatory_changes as rc

# An exposure_tag on a change → the profile.exposures boolean key(s) that satisfy it.
_EXPOSURE_KEYS: dict[str, tuple[str, ...]] = {
    "burn_pit": ("burn_pits",),
    "airborne_hazard": ("burn_pits",),
    "agent_orange": ("agent_orange",),
    "herbicide": ("agent_orange",),
    "gulf_war": ("gulf_war",),
    "radiation": ("radiation",),
    "camp_lejeune": ("camp_lejeune",),
}

# Document types that establish a "you were rated" date, best first.
_RATING_DOC_TYPES = ("rating_decision", "decision_letter")


async def derive_rating_date(db: AsyncSession, uid: str) -> tuple[str | None, str | None]:
    """The veteran's most recent rating date, taken from their OWN rating-decision /
    decision-letter documents (doc_date). Returns (iso_date, source_doc_type), or
    (None, None) if no rating document is on file — the caller then asks the veteran to
    confirm their rating date rather than guessing."""
    rows = (
        await db.execute(
            select(Document.doc_type, Document.doc_date)
            .where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "ready",
                Document.doc_type.in_(_RATING_DOC_TYPES),
                Document.doc_date.is_not(None),
            )
            .order_by(Document.doc_date.desc())
        )
    ).all()
    if not rows:
        return None, None
    doc_type, d = rows[0]
    return d.isoformat(), doc_type


@dataclass
class ChangeMatch:
    change: rc.RegulatoryChange
    matched_by: str  # "condition" | "exposure"
    matched_detail: str  # plain-language why it matched THIS veteran
    action_signal: str  # "review" | "watch" | "check_eligibility"


def _match_change(
    change: rc.RegulatoryChange,
    conditions: list[ClaimedCondition],
    exposures: dict,
) -> ChangeMatch | None:
    """Deterministic match — no AI. A change is relevant if it touches a diagnostic code
    the veteran is claiming, or (for presumptive additions) an exposure in their
    profile. Proposed rules always signal 'watch' (never certain)."""
    dcs = {(c.diagnostic_code or "").strip() for c in conditions if c.diagnostic_code}
    hit_dc = dcs & set(change.diagnostic_codes)
    if hit_dc:
        names = [c.name for c in conditions if (c.diagnostic_code or "").strip() in hit_dc]
        signal = "watch" if change.status == "proposed" else "review"
        return ChangeMatch(
            change,
            "condition",
            f"your condition(s): {', '.join(names)} (DC {', '.join(sorted(hit_dc))})",
            signal,
        )
    if change.exposure_tags and exposures:
        for tag in change.exposure_tags:
            if any(exposures.get(key) for key in _EXPOSURE_KEYS.get(tag, ())):
                signal = "watch" if change.status == "proposed" else "check_eligibility"
                return ChangeMatch(
                    change,
                    "exposure",
                    f"your service exposure: {tag.replace('_', ' ')}",
                    signal,
                )
    return None


async def find_changes(db: AsyncSession, uid: str) -> dict:
    """The deterministic core. Returns the rating date (+ its source) and the list of
    dated changes that post-date it AND touch this veteran's conditions/exposures."""
    rating_date, rating_src = await derive_rating_date(db, uid)
    candidates = rc.changes_after(rating_date)
    conditions = list(
        (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
            )
        ).scalars()
    )
    profile = (
        await db.execute(select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid)))
    ).scalar_one_or_none()
    exposures = (profile.exposures if profile else None) or {}
    matches = [m for change in candidates if (m := _match_change(change, conditions, exposures))]
    return {
        "rating_date": rating_date,
        "rating_date_source": rating_src,
        "matches": matches,
    }


_ASSESS_SYSTEM = (
    "You are a VA-claims self-help assistant. A curated database has already told you "
    "WHAT a regulatory change is and its date — do NOT restate or re-derive it, and do "
    "NOT invent any rule, criterion, or date. Your ONLY job is a person-specific read: "
    "given this veteran's own condition and evidence, is there plausibly enough to act "
    "on this change, and what specific evidence would strengthen it? Educational only. "
    "Never predict what VA will decide, never say they 'qualify' or 'will get' anything. "
    "Frame everything as 'worth discussing with a VSO' and 'you may want to gather'. Be "
    "concrete and brief (2-4 sentences)."
)


async def assess_actionability(
    match: ChangeMatch,
    condition_context: str,
    *,
    model: str | None = None,
) -> str:
    """The ONE AI step — a person-specific read of whether the veteran has enough to act.
    Local model by default (model=None → gateway's llm_model, PII-safe/local). Pass a
    larger allowlisted id to escalate when local quality isn't enough. Never raises —
    on any failure returns '' so the deterministic result still stands on its own."""
    try:
        user = (
            f"Regulatory change (already established — do not restate): "
            f"{match.change.title}. {match.change.summary}\n"
            f"Why it may touch this veteran: {match.matched_detail}\n"
            f"This veteran's own situation: {condition_context}\n\n"
            "Person-specific read only: is there plausibly enough here to act on, and what "
            "specific evidence would they want to gather? 2-4 sentences."
        )
        return await gateway.complete(
            [{"role": "system", "content": _ASSESS_SYSTEM}, {"role": "user", "content": user}],
            model=model,
            temperature=0.2,
            max_tokens=300,
            touches_pii=True,
        )
    except Exception:  # noqa: BLE001 — the AI read is additive; the deterministic result stands
        return ""
